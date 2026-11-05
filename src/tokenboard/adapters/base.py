# -*- coding: utf-8 -*-
"""适配器基类 + 通用字段探测。

各平台的会话日志字段命名差异很大，但 usage 基本逃不出下面几种容器与别名。
这里做**按优先级探测**而不是为每个平台写死解析，好处是：
  * 平台改字段名时通常无需改代码；
  * 用户提供任意 jsonl 也能尽力解析（Generic 适配器）。

探测结果仍然是「尽力而为」：任何无法确认的记录都会被丢弃而不是猜测，
因此统计值可能偏低，但不会凭空造数。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..models import SourceStatus, UsageRecord

# usage 可能出现的容器路径（"" 表示顶层扁平结构）
USAGE_CONTAINERS: tuple[str, ...] = (
    "providerData.rawUsage",
    "providerData.usage",
    "message.usage",
    "response.usage",
    "body.usage",
    "usage",
    "tokens",
    "",
)

INPUT_KEYS = ("prompt_tokens", "input_tokens", "inputTokens", "input", "promptTokens")
OUTPUT_KEYS = ("completion_tokens", "output_tokens", "outputTokens", "output", "completionTokens")
TOTAL_KEYS = ("total_tokens", "totalTokens", "total")

# DeepSeek 风格顶层字段 / OpenAI 风格 details 嵌套字段 / Anthropic 风格
CACHE_READ_KEYS = (
    "prompt_cache_hit_tokens", "cache_read_input_tokens", "cache_read_tokens",
    "cached_tokens", "cacheReadTokens", "cacheRead",
)
CACHE_WRITE_KEYS = (
    "cache_creation_input_tokens", "cache_creation_tokens", "cached_creation_tokens",
    "cache_write_tokens", "cacheWriteTokens", "cacheWrite",
)
DETAIL_KEYS = ("prompt_tokens_details", "input_tokens_details", "cache_tokens_details")

TS_KEYS = ("timestamp", "ts", "time", "created_at", "createdAt", "datetime", "date", "@timestamp")
MODEL_PATHS = (
    "providerData.model", "providerData.requestModelId", "providerData.requestModelName",
    "message.model", "response.model", "model", "modelId", "model_id", "modelName",
)
SESSION_KEYS = ("sessionId", "session_id", "conversationId", "conversation_id", "threadId", "parentSessionId")


def _dig(obj: Any, path: str) -> Any:
    """按点分路径取嵌套值；任一层不是 dict 就返回 None。"""
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _pick_int(box: dict[str, Any], keys: Iterable[str]) -> int:
    """取第一个能转成非负整数的别名值。"""
    for key in keys:
        value = box.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def _pick_str(obj: dict[str, Any], paths_or_keys: Iterable[str]) -> str:
    for path in paths_or_keys:
        value = _dig(obj, path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_usage(obj: dict[str, Any]) -> dict[str, int] | None:
    """从一条日志中抽取 usage；无法确认时返回 ``None``（丢弃该行）。"""
    for path in USAGE_CONTAINERS:
        box = _dig(obj, path)
        if not isinstance(box, dict):
            continue
        inp = _pick_int(box, INPUT_KEYS)
        out = _pick_int(box, OUTPUT_KEYS)
        total = _pick_int(box, TOTAL_KEYS)
        if not (total or inp or out):
            continue

        # 缓存明细可能在 box 里，也可能在 details 子对象里（OpenAI 风格）
        detail: dict[str, Any] = {}
        for dk in DETAIL_KEYS:
            sub = box.get(dk)
            if isinstance(sub, dict):
                detail.update(sub)
        cache_read = _pick_int(box, CACHE_READ_KEYS) or _pick_int(detail, ("cached_tokens", "cache_read_tokens"))
        cache_write = _pick_int(box, CACHE_WRITE_KEYS) or _pick_int(
            detail, ("cached_creation_tokens", "cache_write_tokens", "cache_creation_tokens")
        )
        # 缓存量不可能超过输入量；超出说明字段被重复计数，做 clamp
        cache_read = min(cache_read, inp)
        cache_write = min(cache_write, max(0, inp - cache_read))
        if total <= 0:
            total = inp + out
        return {
            "input_tokens": inp,
            "output_tokens": out,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "total_tokens": total,
        }
    return None


def parse_ts(value: Any) -> int | None:
    """把数字 / ISO8601 / 数字字符串统一成 Unix 秒。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e12:          # 毫秒
            seconds /= 1000.0
        elif seconds <= 1e9:        # 明显不是时间戳（可能是个计数）
            return None
        return int(seconds)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            # 兼容 "2026-11-05T14:38:39.123Z" / "2026-11-05 14:38:39"
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except ValueError:
            pass
        try:
            return parse_ts(float(text))
        except (TypeError, ValueError):
            return None
    return None


def extract_ts(obj: dict[str, Any]) -> int | None:
    for key in TS_KEYS:
        value = obj.get(key)
        if value is None:
            continue
        ts = parse_ts(value)
        if ts is not None:
            return ts
    return None


def extract_model(obj: dict[str, Any], default: str = "unknown") -> str:
    return _pick_str(obj, MODEL_PATHS) or default


def extract_session(obj: dict[str, Any], fallback: str = "") -> str:
    return _pick_str(obj, SESSION_KEYS) or fallback


def workspace_from(path: Path, root: Path | None) -> str:
    """从日志路径推工作空间短名。

    WorkBuddy 的目录是路径 slug（如 ``c-Users-foo-WorkBuddy-2026-08-01-...``），
    取 ``-WorkBuddy-`` 之后的部分；其它平台直接取 root 下第一级目录名。
    """
    base = root or path.parent
    try:
        rel = path.relative_to(base)
    except ValueError:
        rel = Path(path.name)
    parts = rel.parts
    name = parts[0] if len(parts) > 1 else path.stem
    marker = name.rfind("-WorkBuddy-")
    if marker >= 0 and name[marker + 11:]:
        return name[marker + 11:]
    return name


@dataclass(frozen=True, slots=True)
class ParseContext:
    """解析单条日志时的上下文，由文件路径推导一次、全文件复用。"""

    workspace: str
    session_id: str
    path: str


class BaseAdapter:
    """所有平台适配器的基类。

    子类通常只需覆盖 ``name`` / ``display_name`` / ``root_globs`` 三个类属性；
    字段差异靠通用探测兜底，平台特有逻辑再覆盖 ``parse_line``。
    """

    name: str = "base"
    display_name: str = "Base"
    root_globs: tuple[str, ...] = ()
    file_suffixes: tuple[str, ...] = (".jsonl",)
    verified: bool = False
    # 未用真实数据验证过的适配器不参与「无参数自动扫描」，
    # 只能被 --platform / --path 显式指定，防止把配置/记忆目录误当用量日志扫。
    auto_discover: bool = True
    note: str = ""

    def __init__(self, roots: Iterable[str | Path] | None = None) -> None:
        # 显式传入的 roots 优先于默认探测，方便 CI / fixture 测试
        self._roots: list[Path] | None = (
            [Path(r).expanduser() for r in roots] if roots is not None else None
        )

    def candidate_roots(self) -> list[Path]:
        found: list[Path] = []
        for pattern in self.root_globs:
            expanded = os.path.expanduser(pattern)
            # root_globs 是目录通配，不做 recursive **，避免扫到系统目录
            import glob

            for match in sorted(glob.glob(expanded)):
                p = Path(match)
                if p.is_dir() and p not in found:
                    found.append(p)
        return found

    def roots(self) -> list[Path]:
        return self._roots if self._roots is not None else self.candidate_roots()

    def discover(self) -> list[Path]:
        """列出所有候选日志文件（已排序，保证结果可复现）。"""
        files: list[Path] = []
        for root in self.roots():
            if not root.is_dir():
                continue
            for suffix in self.file_suffixes:
                files.extend(root.rglob(f"*{suffix}"))
        return sorted({p for p in files if p.is_file()})

    def status(self) -> SourceStatus:
        roots = tuple(str(r) for r in self.roots())
        return SourceStatus(
            name=self.name,
            display_name=self.display_name,
            verified=self.verified,
            roots=roots,
            file_count=len(self.discover()),
            note=self.note,
        )

    def parse_line(self, obj: dict[str, Any], ctx: ParseContext) -> UsageRecord | None:
        usage = extract_usage(obj)
        ts = extract_ts(obj)
        if usage is None or ts is None:
            return None
        return UsageRecord(
            ts=ts,
            platform=self.name,
            workspace=ctx.workspace,
            session_id=extract_session(obj, ctx.session_id),
            model=extract_model(obj),
            **usage,
        )

    def make_context(self, path: Path, root: Path | None = None) -> ParseContext:
        """由文件路径推导解析上下文；平台可覆盖以处理子代理归属等特例。"""
        base = root or path.parent
        return ParseContext(
            workspace=workspace_from(path, base),
            session_id=path.stem[:16],
            path=str(path),
        )

    def iter_records(self, path: Path, root: Path | None = None) -> Iterator[UsageRecord]:
        """逐行解析一个日志文件；坏行跳过而不是中断整个扫描。"""
        ctx = self.make_context(path, root)
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                record = self.parse_line(obj, ctx)
                if record is not None:
                    yield record

    def iter_json_document(self, path: Path, ctx: ParseContext) -> Iterator[UsageRecord]:
        """解析「整个文件是一个 JSON 对象或数组」的形态（区别于 jsonl 逐行）。

        部分平台（如 OpenCode）落盘的是单文件 JSON，这里复用同一套 parse_line。
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except (json.JSONDecodeError, OSError):
            return
        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            record = self.parse_line(obj, ctx)
            if record is not None:
                yield record

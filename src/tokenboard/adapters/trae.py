# -*- coding: utf-8 -*-
"""Trae / TraeCode 适配器。

Trae 把会话正文与完整历史落在加密的 ``database.db`` 里，明文可读的用量只有
``~/.trae-cn/hub_event_cache/TraeCode/<hub_id>/<task_id>.jsonl`` 事件流：
每行是一个 hub 事件，其中 ``type == "token_usage"`` 携带请求级 token 计数，
``metadata`` / ``model_config`` 提供时间、会话与模型。

统计口径（与通用 ``extract_usage`` 的关键差异）：
  * ``prompt_tokens`` / ``completion_tokens`` 是**本次请求**的输入/输出；
    ``prompt_tokens_total`` / ``completion_tokens_total`` / ``last_turn_total_tokens``
    是累计值，绝不能当成本次请求用量；
  * ``total_tokens`` 为 null 时由输入 + 输出推导；输入/输出缺失但总量可读时反推；
  * 缺失、null、真实 0 三种情况分开记录在 ``UsageRecord.field_states``，
    缺失/null 不能当成 0 参与缓存命中率；
  * ``data`` 兼容 JSON 字符串、对象、双重编码字符串，以及 ``usage`` 等嵌套容器；
  * 同一 ``task_id`` 可以有多次 ``token_usage``（多次请求），按请求逐条累加；
  * 重复写入按 ``(task_id, request_uuid)`` → ``(task_id, seq)`` → 内容指纹去重。

本适配器只解析这份明文事件缓存；加密库内的历史会话不猜测、不伪造。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ..models import UsageRecord
from .base import BaseAdapter, parse_ts

logger = logging.getLogger(__name__)

# 本次请求字段（不含 prompt_tokens_total / completion_tokens_total 等累计值）
_INPUT_KEYS = ("prompt_tokens", "input_tokens", "input")
_OUTPUT_KEYS = ("completion_tokens", "output_tokens", "output")
_TOTAL_KEYS = ("total_tokens", "total")
_CACHE_READ_KEYS = (
    "cache_read_input_tokens", "cache_read_tokens", "cached_tokens",
    "cacheReadTokens", "cacheRead",
)
_CACHE_WRITE_KEYS = (
    "cache_creation_input_tokens", "cache_creation_tokens", "cache_write_tokens",
    "cacheWriteTokens", "cacheWrite",
)
_USAGE_BOX_PATHS = ("", "usage", "token_usage", "rawUsage", "providerData.rawUsage", "data")
_REQUEST_ID_KEYS = ("request_uuid", "request_id", "trace_id")

_ALL_KEYS = set(_INPUT_KEYS + _OUTPUT_KEYS + _TOTAL_KEYS + _CACHE_READ_KEYS + _CACHE_WRITE_KEYS)
_EXCLUDED_DIRS = {"memory", "memories", "cache_memory"}


def _dig(obj: Any, path: str) -> Any:
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


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    """事件里的 ``data`` 可能是 JSON 字符串、对象，或被重复编码的字符串。"""
    raw = event.get("data")
    for _ in range(2):
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            break
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _session_title(data: dict[str, Any]) -> str:
    """从 metadata 的用户消息上下文里取会话标题（Trae 的工作区短名）。"""
    ctx = data.get("user_message_context")
    if not isinstance(ctx, dict):
        return ""
    origins = ctx.get("message_origins")
    if not isinstance(origins, list):
        return ""
    for origin in origins:
        if isinstance(origin, dict):
            title = origin.get("chat_session_title")
            if isinstance(title, str) and title.strip():
                return title.strip()
    return ""


def _session_id(data: dict[str, Any]) -> str:
    value = data.get("session_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    ctx = data.get("user_message_context")
    if isinstance(ctx, dict):
        origins = ctx.get("message_origins")
        if isinstance(origins, list):
            for origin in origins:
                if isinstance(origin, dict):
                    cid = origin.get("chat_session_id")
                    if isinstance(cid, str) and cid.strip():
                        return cid.strip()
    return ""


def _usage_box(data: dict[str, Any]) -> dict[str, Any]:
    """找出真正承载 token 字段的那一层；兼容扁平与嵌套写法。"""
    for path in _USAGE_BOX_PATHS:
        box = _dig(data, path) if path else data
        if isinstance(box, dict) and any(key in box for key in _ALL_KEYS):
            return box
    return data if isinstance(data, dict) else {}


def _read_int(box: dict[str, Any], keys: tuple[str, ...]) -> tuple[int | None, str]:
    """读取一个整数字段并返回 ``(值, 状态)``。

    状态取值：
      ok        读到真实正数
      zero      读到真实 0
      missing   整个字段不存在
      null      字段存在但值为 null
      invalid   字段存在但无法转成整数
    """
    state = "missing"
    for key in keys:
        if key not in box:
            continue
        raw = box[key]
        if raw is None:
            state = "null"
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            state = "invalid"
            continue
        try:
            value = max(0, int(float(raw)))
        except (TypeError, ValueError):
            state = "invalid"
            continue
        return value, ("zero" if value == 0 else "ok")
    return None, state


@dataclass
class _TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    field_states: dict[str, str] = field(default_factory=dict)


def parse_token_usage(data: dict[str, Any]) -> _TokenUsage | None:
    """把一条 ``token_usage`` 的 data 归一成请求级用量；无法确认时返回 None。"""
    box = _usage_box(data)
    inp, inp_state = _read_int(box, _INPUT_KEYS)
    out, out_state = _read_int(box, _OUTPUT_KEYS)
    total, total_state = _read_int(box, _TOTAL_KEYS)
    cache_read, cr_state = _read_int(box, _CACHE_READ_KEYS)
    cache_write, cw_state = _read_int(box, _CACHE_WRITE_KEYS)

    # 真实 0 的总量没有统计意义：若分项可读则按分项求和，否则视为不可用
    if total == 0:
        total, total_state = None, "zero"

    if total is not None:
        # 总量可读时，用总量反推缺失的那一项
        if inp is None and out is not None and total >= out:
            inp, inp_state = total - out, "derived"
        elif out is None and inp is not None and total >= inp:
            out, out_state = total - inp, "derived"
    elif inp is not None and out is not None:
        # total_tokens 为 null / 缺失：由输入 + 输出求和
        total, total_state = inp + out, "derived"

    if total is None:
        # 总量和分项都不完整，无法给出可信的请求级用量
        return None
    if inp is None and out is None:
        # 只有总量：能统计总 Token，但输入/输出拆分不可算，保留并标记
        inp, out = 0, 0
    elif inp is None or out is None:
        # 总量小于已知分项，无法反推另一项
        return None
    if inp == 0 and out == 0 and total == 0:
        return None

    # 缓存字段只在输入可读时 clamp；输入本身缺失（只有 total）时不能拿 0 当基数
    if inp_state not in {"missing", "null", "invalid"}:
        if cache_read is not None:
            cache_read = min(cache_read, inp)
        if cache_write is not None:
            cache_write = min(cache_write, max(0, inp - (cache_read or 0)))

    return _TokenUsage(
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        cache_read_tokens=cache_read or 0,
        cache_write_tokens=cache_write or 0,
        field_states={
            "input_tokens": inp_state,
            "output_tokens": out_state,
            "total_tokens": total_state,
            "cache_read_tokens": cr_state,
            "cache_write_tokens": cw_state,
        },
    )


@dataclass
class _TaskInfo:
    first_ts: int | None = None
    session: str = ""
    workspace: str = ""
    model: str = ""


def _task_id(event: dict[str, Any], fallback: str) -> str:
    value = event.get("task_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _dedup_key(
    task_id: str,
    event: dict[str, Any],
    data: dict[str, Any],
    usage: _TokenUsage,
) -> tuple:
    """可验证的去重键：同一请求被重试或多份缓存重复写入时保持唯一。

    优先级：
      1. ``(task_id, request_uuid/request_id/trace_id)`` —— 请求级唯一标识；
      2. ``(task_id, reply_to_message_id)`` —— 仅当它不等于 task_id（真实数据里等于）；
      3. ``(task_id, seq)`` —— hub 事件序号，同一 task 的多次请求序号不同；
      4. ``(task_id, 内容指纹)`` —— 无序号时的兜底。
    """
    for key in _REQUEST_ID_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return (task_id, key, value.strip())
        if isinstance(value, int) and not isinstance(value, bool):
            return (task_id, key, str(value))

    reply = data.get("reply_to_message_id")
    if isinstance(reply, str) and reply.strip() and reply.strip() != task_id:
        return (task_id, "reply_to_message_id", reply.strip())

    seq = event.get("seq")
    if seq is not None:
        return (task_id, "seq", str(seq))

    return (
        task_id,
        "fingerprint",
        usage.input_tokens,
        usage.output_tokens,
        usage.total_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
    )


def _iter_events(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    """逐行读取事件；坏行/坏对象记录明确日志后跳过。"""
    try:
        fh = path.open("r", encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.error("[trae][ERROR] 无法读取事件文件 %s: %s", path, exc)
        return
    with fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning("[trae][WARN] %s:%d JSON 解析失败，已跳过：%s", path, lineno, exc)
                continue
            if isinstance(obj, dict):
                yield lineno, obj
            elif isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        yield lineno, item
                    else:
                        logger.warning("[trae][WARN] %s:%d 数组元素不是对象，已跳过", path, lineno)
            else:
                logger.warning("[trae][WARN] %s:%d 事件不是对象，已跳过", path, lineno)


class TraeAdapter(BaseAdapter):
    name = "trae"
    display_name = "Trae / TraeCode"
    root_globs = (
        "~/.trae-cn/hub_event_cache",
        "~/.trae/hub_event_cache",
        "~/Library/Application Support/Trae CN/hub_event_cache",
        "~/Library/Application Support/Trae/hub_event_cache",
    )
    verified = True
    # 默认扫描仍然只覆盖已验证且自动发现的平台；trae 需要显式 --platform trae，
    # 避免把只有部分事件的缓存混进其他平台的无参数看板。
    auto_discover = False
    note = (
        "解析 hub_event_cache 中 type=token_usage 的请求级事件；"
        "按 task_id + 请求 ID / seq 去重；缓存字段缺失记为未知而非 0；"
        "本机其余 Trae 会话历史存放在加密 database.db，明文不可读，因此统计可能偏低"
    )

    def discover(self) -> list[Path]:
        """只接受 hub_event_cache 下至少两级目录内的事件流。

        根目录 ``~/.trae-cn`` 里还有 memory 等无关目录；即使误把根路径配进来，
        也不会把单层散落的 jsonl 或 memory 文件当作 token 用量。
        """
        files = super().discover()
        kept: list[Path] = []
        for path in files:
            rel = None
            for root in self.roots():
                try:
                    rel = path.relative_to(root)
                    break
                except ValueError:
                    continue
            if rel is None or len(rel.parts) < 2:
                continue
            if any(part.lower() in _EXCLUDED_DIRS for part in rel.parts[:-1]):
                continue
            kept.append(path)
        return kept

    def iter_records(self, path: Path, root: Path | None = None) -> Iterator[UsageRecord]:
        ctx = self.make_context(path, root)
        events = list(_iter_events(path))
        if not events:
            return

        # 第一遍：建立 task_id → 时间/会话/标题/模型（token_usage 本身不带这些）
        infos: dict[str, _TaskInfo] = {}
        for _lineno, event in events:
            task_id = _task_id(event, path.stem)
            data = _event_data(event)
            kind = event.get("type")
            info = infos.setdefault(task_id, _TaskInfo())

            ts = parse_ts(data.get("created_at"))
            if ts is not None and (info.first_ts is None or ts < info.first_ts):
                info.first_ts = ts

            if kind in ("metadata", "message_context_update", "append_input"):
                sid = _session_id(data)
                if sid and not info.session:
                    info.session = sid
                title = _session_title(data)
                if title and not info.workspace:
                    info.workspace = title
            elif kind == "model_config":
                model = data.get("config_name") or data.get("model_name")
                if isinstance(model, str) and model.strip() and not info.model:
                    info.model = model.strip()
            elif kind == "timing_events" and not info.model:
                model = data.get("model_name")
                if isinstance(model, str) and model.strip():
                    info.model = model.strip()

        # 第二遍：逐条产出 token_usage；用事件流里最近的 created_at 作为请求时间
        seen: set[tuple] = set()
        current_ts: dict[str, int] = {}
        warned_time: set[str] = set()
        warned_model: set[str] = set()

        for lineno, event in events:
            task_id = _task_id(event, path.stem)
            data = _event_data(event)
            kind = event.get("type")

            ts = parse_ts(data.get("created_at"))
            if ts is not None:
                current_ts[task_id] = ts

            if kind != "token_usage":
                continue

            usage = parse_token_usage(data)
            if usage is None:
                logger.error(
                    "[trae][ERROR] %s:%d task=%s 的 token_usage 缺少可用字段，已跳过：keys=%s",
                    path, lineno, task_id, sorted(_usage_box(data).keys()),
                )
                continue

            key = _dedup_key(task_id, event, data, usage)
            if key in seen:
                logger.debug("[trae][DEBUG] %s:%d 重复事件已去重：%s", path, lineno, key)
                continue
            seen.add(key)

            info = infos.get(task_id, _TaskInfo())
            record_ts = current_ts.get(task_id)
            if record_ts is None:
                record_ts = info.first_ts
            if record_ts is None:
                try:
                    record_ts = int(path.stat().st_mtime)
                except OSError as exc:
                    logger.error("[trae][ERROR] %s 无法读取 mtime，事件被跳过：%s", path, exc)
                    continue
                if task_id not in warned_time:
                    warned_time.add(task_id)
                    logger.warning(
                        "[trae][WARN] task=%s 缺少 metadata.created_at，时间回退到文件 mtime",
                        task_id,
                    )

            model = info.model or "unknown"
            if model == "unknown" and task_id not in warned_model:
                warned_model.add(task_id)
                logger.warning(
                    "[trae][WARN] task=%s 缺少 model_config / timing_events 模型信息，模型记为 unknown",
                    task_id,
                )

            session = info.session or ctx.session_id
            workspace = info.workspace or ctx.workspace
            yield UsageRecord(
                ts=record_ts,
                platform=self.name,
                workspace=workspace,
                session_id=session,
                model=model,
                title=info.workspace or session,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                total_tokens=usage.total_tokens,
                field_states=usage.field_states,
                dedup_key=f"{self.name}|" + "|".join(str(part) for part in key),
            )

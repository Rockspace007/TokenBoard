# -*- coding: utf-8 -*-
"""外部用量文件导入适配器。

Trae 的完整会话历史落在 SQLCipher 加密的 ``database.db`` 里，本机没有可直接
使用的密钥；官方客户端导出的用量表（CSV / JSON）则可以作为兜底来源。本适配器
只做「文件 → UsageRecord」的归一化，不发起任何网络请求。

支持：
  * ``.csv``：``csv.DictReader``，兼容 UTF-8 BOM；
  * ``.json``：整文件数组、``{"records": [...]}`` 包装、单个对象；
  * ``.jsonl``：逐行 JSON；
  * 字段映射可配（``mapping``：UsageRecord 字段名 → 源列名 / JSON 点分路径），
    未配置的字段回落到 ``base.extract_usage`` / ``extract_ts`` / ``extract_model``
    的通用别名探测。
"""
from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Iterator

from ..models import SourceStatus, UsageRecord
from .base import (
    CACHE_READ_KEYS,
    CACHE_WRITE_KEYS,
    INPUT_KEYS,
    OUTPUT_KEYS,
    TOTAL_KEYS,
    BaseAdapter,
    ParseContext,
    extract_model,
    extract_session,
    extract_ts,
    extract_usage,
    parse_ts,
)

logger = logging.getLogger(__name__)

_TOKEN_FIELDS: dict[str, tuple[str, ...]] = {
    "input_tokens": INPUT_KEYS,
    "output_tokens": OUTPUT_KEYS,
    "total_tokens": TOTAL_KEYS,
    "cache_read_tokens": CACHE_READ_KEYS,
    "cache_write_tokens": CACHE_WRITE_KEYS,
}

MAPPING_FIELDS = {
    "ts", "platform", "workspace", "session_id", "model", "title",
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "total_tokens", "dedup_key",
}

_UNKNOWN_STATES = {"missing", "null", "invalid"}
_JSON_LIST_KEYS = ("records", "data", "items", "usages")
_MISSING = object()

# 自动探测「哪个数组是用量记录」时用的键名（含常见 usage 容器）
_USAGE_HINT_KEYS = frozenset(
    INPUT_KEYS + OUTPUT_KEYS + TOTAL_KEYS + CACHE_READ_KEYS + CACHE_WRITE_KEYS
    + ("usage", "tokens", "tokenUsage", "usageDetails")
)


def _dig(obj: Any, path: str) -> Any:
    """按点分路径取嵌套值；顶层同名键优先（CSV 列名可能本身带点）。"""
    if not isinstance(obj, dict):
        return None
    if path in obj:
        return obj[path]
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _has_usage_hint(row: Any) -> bool:
    """一条对象里是否出现用量字段（允许多嵌套一层容器，如 ``usage``）。"""
    if not isinstance(row, dict):
        return False
    for key, value in row.items():
        if key in _USAGE_HINT_KEYS:
            return True
        if isinstance(value, dict) and any(k in _USAGE_HINT_KEYS for k in value):
            return True
    return False


def _find_record_list(node: Any, depth: int = 0) -> tuple[str, list] | None:
    """在未知结构的 JSON 里找第一个像用量记录的数组，返回 ``(点分路径, 数组)``。

    只下钻两层以内，避免把深层无关数组（如权限列表）误判为记录集。
    """
    if depth > 2 or not isinstance(node, (dict, list)):
        return None

    if isinstance(node, list):
        if any(_has_usage_hint(item) for item in node[:5]):
            return "", node
        for index, item in enumerate(node[:5]):
            found = _find_record_list(item, depth + 1)
            if found is not None:
                path, records = found
                prefix = str(index)
                return (f"{prefix}.{path}" if path else prefix), records
        return None

    for key in _JSON_LIST_KEYS:
        child = node.get(key)
        if isinstance(child, list):
            found = _find_record_list(child, depth + 1)
            if found is not None:
                path, records = found
                return (f"{key}.{path}" if path else key), records
    for key, child in node.items():
        if isinstance(child, (dict, list)):
            found = _find_record_list(child, depth + 1)
            if found is not None:
                path, records = found
                return (f"{key}.{path}" if path else key), records
    return None


def _resolve_path(obj: Any, path: str) -> Any:
    """按点分路径取子节点；任一层缺失返回 ``None``。"""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _read_int(raw: Any) -> tuple[int | None, str]:
    """读取一个整数字段并返回 ``(值, 状态)``；状态区分缺失 / null / 真实 0。"""
    if raw is None:
        return None, "null"
    if isinstance(raw, str) and not raw.strip():
        return None, "missing"
    if isinstance(raw, bool):
        return None, "invalid"
    try:
        value = max(0, int(float(raw)))
    except (TypeError, ValueError):
        return None, "invalid"
    return value, ("zero" if value == 0 else "ok")


def _finalize_usage(values: dict[str, int | None], states: dict[str, str]) -> dict[str, Any] | None:
    """补全总量 / 输入输出，规则与 Trae 适配器保持一致。"""
    inp, out, total = values["input_tokens"], values["output_tokens"], values["total_tokens"]

    if total is None:
        if inp is not None and out is not None:
            total, states["total_tokens"] = inp + out, "derived"
    else:
        if inp is None and out is not None and total >= out:
            inp, states["input_tokens"] = total - out, "derived"
        elif out is None and inp is not None and total >= inp:
            out, states["output_tokens"] = total - inp, "derived"

    if total is None:
        return None
    if inp is None and out is None:
        inp, out = 0, 0
    elif inp is None or out is None:
        return None
    if inp == 0 and out == 0 and total == 0:
        return None

    cache_read, cache_write = values["cache_read_tokens"], values["cache_write_tokens"]
    if states["input_tokens"] not in _UNKNOWN_STATES:
        if cache_read is not None:
            cache_read = min(cache_read, inp)
        if cache_write is not None:
            cache_write = min(cache_write, max(0, inp - (cache_read or 0)))

    return {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": total,
        "cache_read_tokens": cache_read or 0,
        "cache_write_tokens": cache_write or 0,
        "field_states": states,
    }


class ExternalAdapter(BaseAdapter):
    """把用户导出的 CSV / JSON 用量文件归一成请求级记录。"""

    name = "external"
    display_name = "外部用量文件"
    root_globs = ()
    file_suffixes = (".csv", ".json", ".jsonl")
    verified = True
    auto_discover = False
    note = "导入 CSV/JSON 用量文件；字段映射可用 --map 覆盖，未映射字段走通用别名探测"

    def __init__(
        self,
        paths: list[str | Path],
        platform: str = "external",
        mapping: dict[str, str] | None = None,
        records_path: str | None = None,
    ) -> None:
        super().__init__(roots=paths)
        self.platform = (platform or "external").strip() or "external"
        self.mapping = dict(mapping or {})
        self.records_path = (records_path or "").strip() or None

    def discover(self) -> list[Path]:
        files: list[Path] = []
        for root in self.roots():
            if root.is_file():
                if root.suffix.lower() in self.file_suffixes:
                    files.append(root)
            elif root.is_dir():
                for suffix in self.file_suffixes:
                    files.extend(root.rglob(f"*{suffix}"))
        return sorted({p for p in files if p.is_file()})

    def _row_get(self, row: dict[str, Any], field: str) -> Any:
        key = self.mapping.get(field)
        return _dig(row, key) if key else None

    def parse_row(
        self,
        row: dict[str, Any],
        ctx: ParseContext,
        fallback_ts: int | None = None,
    ) -> UsageRecord | None:
        fallback = extract_usage(row) or {}
        values: dict[str, int | None] = {}
        states: dict[str, str] = {}
        explicit = False
        for field, aliases in _TOKEN_FIELDS.items():
            if field in self.mapping:
                explicit = True
                values[field], states[field] = _read_int(self._row_get(row, field))
                continue
            raw = next((row[alias] for alias in aliases if alias in row), _MISSING)
            if raw is not _MISSING:
                values[field], states[field] = _read_int(raw)
            elif field in fallback:
                values[field], states[field] = fallback[field], ("derived" if field == "total_tokens" else "ok")
            else:
                values[field], states[field] = None, "missing"

        if not explicit and not fallback:
            logger.warning("[external][WARN] %s 第 %s 条没有可用 usage 字段，已跳过", ctx.path, ctx.session_id)
            return None

        usage = _finalize_usage(values, states)
        if usage is None:
            logger.error("[external][ERROR] %s 的 usage 无法归一（输入/输出/总量不足）：%r", ctx.path, row)
            return None

        raw_ts = self._row_get(row, "ts") if "ts" in self.mapping else None
        ts = parse_ts(raw_ts) if raw_ts is not None else None
        if ts is None:
            ts = extract_ts(row)
        if ts is None:
            ts = fallback_ts
            if ts is not None:
                logger.warning("[external][WARN] %s 缺少时间戳，回退到文件 mtime", ctx.path)
        if ts is None:
            logger.warning("[external][WARN] %s 缺少时间戳且无法读取文件 mtime，跳过", ctx.path)
            return None

        platform = (self._row_get(row, "platform") if "platform" in self.mapping else None) or self.platform
        workspace = (self._row_get(row, "workspace") if "workspace" in self.mapping else None) or ctx.workspace
        session_id = (
            self._row_get(row, "session_id") if "session_id" in self.mapping else None
        ) or extract_session(row, ctx.session_id)
        model = (self._row_get(row, "model") if "model" in self.mapping else None) or extract_model(row)
        title = (self._row_get(row, "title") if "title" in self.mapping else None) or ""

        dedup = self._row_get(row, "dedup_key") if "dedup_key" in self.mapping else None
        key = str(dedup) if dedup else f"{platform}|{ts}|{session_id}|{model}|{usage['total_tokens']}"

        return UsageRecord(
            ts=ts,
            platform=str(platform),
            workspace=str(workspace),
            session_id=str(session_id),
            model=str(model),
            title=str(title) if title is not None else "",
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cache_read_tokens=usage["cache_read_tokens"],
            cache_write_tokens=usage["cache_write_tokens"],
            total_tokens=usage["total_tokens"],
            field_states=usage["field_states"],
            dedup_key=key,
        )

    def _iter_file(self, path: Path, ctx: ParseContext, fallback_ts: int | None) -> Iterator[UsageRecord]:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as fh:
                for row in csv.DictReader(fh):
                    record = self.parse_row(dict(row), ctx, fallback_ts)
                    if record is not None:
                        yield record
            return

        if suffix == ".jsonl":
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("[external][WARN] %s 存在坏行，已跳过", path)
                        continue
                    if not isinstance(obj, dict):
                        continue
                    record = self.parse_row(obj, ctx, fallback_ts)
                    if record is not None:
                        yield record
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8-sig", errors="ignore"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("[external][ERROR] %s 无法解析 JSON：%s", path, exc)
            return
        if self.records_path:
            data = _resolve_path(data, self.records_path)
            if isinstance(data, dict):
                data = [data]
            elif not isinstance(data, list):
                logger.error(
                    "[external][ERROR] %s 中找不到记录数组 %r；用 --records 指定正确的点分路径",
                    path, self.records_path,
                )
                return
        elif isinstance(data, dict):
            found = _find_record_list(data)
            if found is not None:
                _, data = found
                logger.info("[external] %s 自动定位记录数组：%s", path, found[0] or "(顶层)")
            else:
                data = [data]
        if not isinstance(data, list):
            logger.error("[external][ERROR] %s 顶层不是对象或数组，已跳过", path)
            return
        for obj in data:
            if not isinstance(obj, dict):
                continue
            record = self.parse_row(obj, ctx, fallback_ts)
            if record is not None:
                yield record

    def iter_records(self, path: Path, root: Path | None = None) -> Iterator[UsageRecord]:
        ctx = self.make_context(path, root)
        try:
            fallback_ts = int(path.stat().st_mtime)
        except OSError:
            fallback_ts = None
        if fallback_ts is None:
            logger.warning("[external][WARN] %s 无法读取 mtime，缺时间戳的行会被跳过", path)
        yield from self._iter_file(path, ctx, fallback_ts)

    def iter_all_records(self) -> Iterator[UsageRecord]:
        """按 dedup_key 去重，避免同一份导出被重复导入时重复计数。"""
        seen: set[str] = set()
        root = self.roots()[0] if self.roots() else None
        for path in self.discover():
            for record in self.iter_records(path, root):
                key = record.dedup_key
                if key in seen:
                    continue
                seen.add(key)
                yield record

    def status(self) -> SourceStatus:
        roots = tuple(str(r) for r in self.roots())
        return SourceStatus(
            name=self.name,
            display_name=self.display_name,
            verified=True,
            roots=roots,
            file_count=len(self.discover()),
            note=self.note,
        )

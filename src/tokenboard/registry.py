# -*- coding: utf-8 -*-
"""适配器注册表与统一扫描入口。

CLI 与 MCP Server 都只调用 :func:`scan`，保证两个入口口径完全一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .adapters.base import BaseAdapter
from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.codex import CodexAdapter
from .adapters.generic import GenericAdapter
from .adapters.opencode import OpenCodeAdapter
from .adapters.trae import TraeAdapter
from .adapters.workbuddy import WorkBuddyAdapter
from .models import SourceStatus, UsageRecord

ADAPTER_CLASSES: dict[str, type[BaseAdapter]] = {
    "workbuddy": WorkBuddyAdapter,
    "claude_code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "trae": TraeAdapter,
    "opencode": OpenCodeAdapter,
    "generic": GenericAdapter,
}

# 用户口中的平台名 → 内部 key（含用户提到的 treacode / claudecode 写法）
ALIASES: dict[str, str] = {
    "claudecode": "claude_code",
    "claude-code": "claude_code",
    "claude": "claude_code",
    "claude_code": "claude_code",
    "treacode": "trae",
    "traecode": "trae",
    "trae_code": "trae",
    "open-code": "opencode",
    "open_code": "opencode",
    "work-buddy": "workbuddy",
    "wb": "workbuddy",
}


def normalize(name: str) -> str:
    key = name.strip().lower().replace(" ", "_")
    return ALIASES.get(key, key)


def names() -> list[str]:
    return list(ADAPTER_CLASSES)


def get(name: str, roots: Iterable[str | Path] | None = None) -> BaseAdapter:
    key = normalize(name)
    if key not in ADAPTER_CLASSES:
        raise KeyError(f"未知平台 {name!r}；可选：{', '.join(names())}")
    return ADAPTER_CLASSES[key](roots=list(roots) if roots is not None else None)


def all_adapters() -> list[BaseAdapter]:
    """自动发现用的适配器列表；generic 无默认路径，不参与自动扫描。"""
    return [cls() for cls in ADAPTER_CLASSES.values() if cls.name != "generic"]


@dataclass
class ScanResult:
    records: list[UsageRecord] = field(default_factory=list)
    statuses: list[SourceStatus] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)

    def to_dict(self) -> dict:
        return {
            "record_count": self.count,
            "sources": [s.to_dict() for s in self.statuses],
            "errors": list(self.errors),
        }


def _root_for(adapter: BaseAdapter, path: Path) -> Path:
    """找出文件属于哪个 root，供子代理路径归属计算使用。"""
    for root in adapter.roots():
        try:
            path.relative_to(root)
            return root
        except ValueError:
            continue
    return path.parent


def scan(
    platforms: Sequence[str] | None = None,
    paths: Sequence[str | Path] | None = None,
    since: int | None = None,
    until: int | None = None,
) -> ScanResult:
    """扫描一个或多个平台，返回归一化的请求级记录。

    ``paths`` 优先：给定后只走 GenericAdapter（适合新平台探路与 CI fixture）。
    ``since`` / ``until`` 为 Unix 秒，闭开区间 ``[since, until)``。
    """
    result = ScanResult()
    adapters: list[BaseAdapter] = []

    # 数据源状态表始终展示全部平台（含未验证），但只有 auto_discover 的平台
    # 参与「无参数自动扫描」，避免把未确认的目录当日志扫进来制造噪声。
    result.statuses = [a.status() for a in all_adapters()]

    if paths:
        adapters.append(GenericAdapter(roots=[Path(p).expanduser() for p in paths]))
        result.statuses.append(adapters[0].status())
    elif platforms:
        for name in platforms:
            try:
                adapters.append(get(name))
            except KeyError as exc:
                result.errors.append(str(exc))
    else:
        adapters = [a for a in all_adapters() if a.auto_discover]

    for adapter in adapters:
        try:
            for file in adapter.discover():
                for record in adapter.iter_records(file, _root_for(adapter, file)):
                    if since is not None and record.ts < since:
                        continue
                    if until is not None and record.ts >= until:
                        continue
                    result.records.append(record)
        except (OSError, ValueError) as exc:
            # 单个平台出错不能拖垮整次扫描，记录后继续
            result.errors.append(f"[{adapter.name}] {type(exc).__name__}: {exc}")

    # 同一文件可能被多个 root 通配命中，按内容指纹去重，避免重复计数
    seen: set[tuple] = set()
    unique: list[UsageRecord] = []
    for rec in result.records:
        key = (rec.ts, rec.platform, rec.session_id, rec.model, rec.total_tokens, rec.input_tokens)
        if key in seen:
            continue
        seen.add(key)
        unique.append(rec)
    result.records = unique
    return result

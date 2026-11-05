# -*- coding: utf-8 -*-
"""统一数据模型。

所有平台的日志最终都归一为 :class:`UsageRecord`，下游聚合、计价、渲染
只认这一种结构；新增平台时只需写一个新的 adapter，不用改统计逻辑。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """一条**请求级** usage 记录（不是会话汇总）。

    ts                 Unix 秒（统一为秒，毫秒入参会自动换算）
    platform           来源平台标识，如 workbuddy / claude_code / codex
    workspace          工作空间短名
    session_id         会话 ID；子代理日志应归属父会话
    model              归一化后的模型名
    total_tokens       缺省时由 input + output 推导
    """

    ts: int
    platform: str
    workspace: str
    session_id: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        # frozen dataclass 只能通过 object.__setattr__ 补默认值
        if self.total_tokens <= 0:
            object.__setattr__(
                self,
                "total_tokens",
                max(0, self.input_tokens) + max(0, self.output_tokens),
            )
        # 防御脏数据：字段全转 int 且负值归零，避免聚合出负成本
        for fname in (
            "ts",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "total_tokens",
        ):
            value = getattr(self, fname)
            try:
                ivalue = int(value)
            except (TypeError, ValueError):
                ivalue = 0
            object.__setattr__(self, fname, max(0, ivalue) if fname != "ts" else ivalue)

    @property
    def non_cached_input(self) -> int:
        """未命中缓存、也未用于缓存写入的普通输入 token。"""
        return max(0, self.input_tokens - self.cache_read_tokens - self.cache_write_tokens)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UsageRecord":
        """从字典构造，自动忽略未知键（便于读取外部 JSON 不改代码）。"""
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(frozen=True, slots=True)
class SourceStatus:
    """一个平台适配器在本机的数据源状态，用于 CLI / MCP 自检。"""

    name: str
    display_name: str
    verified: bool
    roots: tuple[str, ...]
    file_count: int
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "verified": self.verified,
            "roots": list(self.roots),
            "file_count": self.file_count,
            "note": self.note,
        }

# -*- coding: utf-8 -*-
"""聚合统计：把请求级记录压成看板所需的全部指标。

所有入口（CLI / MCP / Skill）共用本模块，避免同一份数据在不同入口算出不同结果。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from .brands import palette_for, vendor_of
from .models import UsageRecord
from .pricing import cost_cny


@dataclass
class Summary:
    records: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_cny: float = 0.0
    sessions: int = 0
    workspaces: int = 0
    first_ts: int | None = None
    last_ts: int | None = None
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_platform: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_workspace: dict[str, dict[str, Any]] = field(default_factory=dict)
    daily: dict[str, int] = field(default_factory=dict)
    hourly: list[int] = field(default_factory=lambda: [0] * 24)
    bands: list[int] = field(default_factory=lambda: [0, 0, 0, 0])  # 0-6/6-12/12-18/18-24

    @property
    def models(self) -> list[str]:
        return sorted(self.by_model, key=lambda m: -self.by_model[m]["tokens"])

    @property
    def platforms(self) -> list[str]:
        return sorted(self.by_platform, key=lambda p: -self.by_platform[p]["tokens"])

    @property
    def active_days(self) -> int:
        return len(self.daily)

    @property
    def cache_hit_rate(self) -> float:
        return (self.cache_read_tokens / self.input_tokens * 100.0) if self.input_tokens else 0.0

    @property
    def io_ratio(self) -> float:
        return (self.input_tokens / self.output_tokens) if self.output_tokens else 0.0

    @property
    def daily_average(self) -> float:
        return self.total_tokens / self.active_days if self.active_days else 0.0

    @property
    def price_per_million(self) -> float:
        """折合每百万 token 的实际单价（元），便于跨模型比较。"""
        return (self.cost_cny / self.total_tokens * 1_000_000) if self.total_tokens else 0.0

    def kpi(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "daily_average": round(self.daily_average, 1),
            "requests": self.records,
            "sessions": self.sessions,
            "workspaces": self.workspaces,
            "input_output_ratio": round(self.io_ratio, 2),
            "cache_hit_rate": round(self.cache_hit_rate, 2),
            "estimated_cost_cny": round(self.cost_cny, 2),
            "price_per_million_cny": round(self.price_per_million, 2),
            "active_days": self.active_days,
        }

    def to_dict(self) -> dict[str, Any]:
        palette = palette_for(self.models)
        return {
            "kpi": self.kpi(),
            "models": [
                {"name": m, **self.by_model[m], "color": palette[m], "vendor": vendor_of(m)}
                for m in self.models
            ],
            "platforms": [
                {"name": p, **v}
                for p, v in sorted(self.by_platform.items(), key=lambda kv: -kv[1]["tokens"])
            ],
            "workspaces": [
                {"name": w, **v}
                for w, v in sorted(self.by_workspace.items(), key=lambda kv: -kv[1]["tokens"])
            ],
            "daily": [{"date": d, "tokens": t} for d, t in sorted(self.daily.items())],
            "hourly": list(self.hourly),
            "bands": list(self.bands),
            "coverage": {
                "first_ts": self.first_ts,
                "last_ts": self.last_ts,
                "active_days": self.active_days,
            },
        }


def _bucket(store: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    return store.setdefault(key, {"tokens": 0, "requests": 0, "cost": 0.0})


def summarize(records: Iterable[UsageRecord], prices: dict | None = None) -> Summary:
    """汇总请求级记录。传入空列表返回全零 Summary，调用方无需特判。"""
    summary = Summary()
    sessions: set[tuple[str, str]] = set()

    for rec in records:
        summary.records += 1
        summary.total_tokens += rec.total_tokens
        summary.input_tokens += rec.input_tokens
        summary.output_tokens += rec.output_tokens
        summary.cache_read_tokens += rec.cache_read_tokens
        summary.cache_write_tokens += rec.cache_write_tokens
        summary.cost_cny += cost_cny(rec, prices)

        if summary.first_ts is None or rec.ts < summary.first_ts:
            summary.first_ts = rec.ts
        if summary.last_ts is None or rec.ts > summary.last_ts:
            summary.last_ts = rec.ts

        m = _bucket(summary.by_model, rec.model)
        m["tokens"] += rec.total_tokens
        m["requests"] += 1
        m["cost"] += cost_cny(rec, prices)

        p = _bucket(summary.by_platform, rec.platform)
        p["tokens"] += rec.total_tokens
        p["requests"] += 1

        w = _bucket(summary.by_workspace, rec.workspace)
        w["tokens"] += rec.total_tokens
        w["requests"] += 1

        sessions.add((rec.platform, rec.session_id))

        # 时间维度统一按**本机时区**解释，与用户看到的日志时间一致
        dt = datetime.fromtimestamp(rec.ts)
        day = dt.strftime("%Y-%m-%d")
        summary.daily[day] = summary.daily.get(day, 0) + rec.total_tokens
        summary.hourly[dt.hour] += rec.total_tokens
        summary.bands[min(3, dt.hour // 6)] += rec.total_tokens

    summary.sessions = len(sessions)
    summary.workspaces = len(summary.by_workspace)
    return summary

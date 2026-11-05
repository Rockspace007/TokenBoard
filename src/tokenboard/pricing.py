# -*- coding: utf-8 -*-
"""计价：按每条请求的**实际缓存命中**算钱，而不是拿总 token 乘单价。

单位统一为 **元 / 百万 token**。价格表是"牌价"，不同套餐、不同网关差异很大，
生产环境应通过 ``--prices <json>`` 覆盖，代码不内置任何账号相关凭据。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import UsageRecord

# (输入价, 输出价, 缓存命中读取价)  单位：元 / 百万 token
DEFAULT_PRICES: dict[str, tuple[float, float, float]] = {
    "deepseek": (2.0, 8.0, 0.5),
    "hy": (1.0, 4.0, 0.2),
    "hunyuan": (1.0, 4.0, 0.2),
    "claude": (21.0, 105.0, 2.1),
    "sonnet": (21.0, 105.0, 2.1),
    "opus": (105.0, 525.0, 10.5),
    "haiku": (5.0, 25.0, 0.5),
    "gpt": (14.0, 56.0, 1.4),
    "o1": (14.0, 56.0, 1.4),
    "o3": (14.0, 56.0, 1.4),
    "o4": (14.0, 56.0, 1.4),
    "codex": (14.0, 56.0, 1.4),
    "glm": (2.0, 8.0, 0.4),
    "qwen": (2.0, 8.0, 0.4),
    "gemini": (7.0, 21.0, 0.7),
    "kimi": (2.0, 8.0, 0.4),
    "llama": (2.0, 8.0, 0.4),
    "mistral": (2.0, 8.0, 0.4),
    "grok": (2.0, 8.0, 0.4),
    "auto": (2.0, 8.0, 0.4),
}
FALLBACK_PRICE: tuple[float, float, float] = (2.0, 8.0, 0.4)

# Claude 系缓存写入按输入价的 1.25 倍计（与上游 skill 口径一致）
CACHE_WRITE_MULTIPLIER = 1.25


@dataclass(frozen=True, slots=True)
class Price:
    input: float
    output: float
    cache_read: float
    cache_write_multiplier: float = CACHE_WRITE_MULTIPLIER


def price_of(model: str, table: dict[str, tuple[float, float, float]] | None = None) -> Price:
    """按模型名前缀匹配价格表。"""
    prices = table or DEFAULT_PRICES
    name = (model or "").strip().lower()
    for key, triple in prices.items():
        if name.startswith(key):
            return Price(*triple)
    return Price(*FALLBACK_PRICE)


def load_prices(path: str | Path | None) -> dict[str, tuple[float, float, float]]:
    """从 JSON 文件合并自定义价格：``{"glm": [2, 8, 0.4], ...}``。"""
    table = dict(DEFAULT_PRICES)
    if not path:
        return table
    data: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("价格表必须是 {模型前缀: [输入, 输出, 缓存读取]} 的 JSON 对象")
    for key, triple in data.items():
        if not (isinstance(triple, (list, tuple)) and len(triple) == 3):
            raise ValueError(f"价格项 {key!r} 必须是长度为 3 的数组")
        table[str(key).lower()] = tuple(float(x) for x in triple)  # type: ignore[assignment]
    return table


def cost_cny(record: UsageRecord, prices: dict[str, tuple[float, float, float]] | None = None) -> float:
    """单条请求的人民币成本。

    口径与参考实现一致：
      * 缓存读命中 → 走 cache_read 价
      * 缓存写入   → 输入价 × 1.25
      * 其余输入   → 输入价
      * 输出       → 输出价
    cache_read / cache_write 都会被 clamp 到 input_tokens 内，防止脏数据算出负数。
    """
    p = price_of(record.model, prices)
    cached_read = min(max(0, record.cache_read_tokens), max(0, record.input_tokens))
    remaining = max(0, record.input_tokens - cached_read)
    cached_write = min(max(0, record.cache_write_tokens), remaining)
    plain_input = max(0, remaining - cached_write)
    total = (
        cached_read * p.cache_read
        + cached_write * p.input * p.cache_write_multiplier
        + plain_input * p.input
        + max(0, record.output_tokens) * p.output
    )
    return total / 1_000_000.0

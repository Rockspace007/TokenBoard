# -*- coding: utf-8 -*-
"""绿色系主题令牌 + 模型厂商品牌色映射。

设计约定（渲染层与设计稿共用，改动需同步 docs/DESIGN_TOKENS.md）：

* **绿色系只出现在 UI 框架**：背景、卡片、边框、文字、主按钮、热力色阶。
* **品牌色只出现在数据系列**：图表柱/线、图例点、模型徽标。
* 品牌色**必须同时带文字标签**，不能只靠颜色区分（WCAG 1.4.1）。
* OpenAI 的品牌绿与主题主色接近，因此所有数据系列额外加 1px 深色描边。

主题与品牌色是两层正交的令牌，互不覆盖；这样"统一绿色系"和
"按模型匹配品牌色"两个要求不会互相打架。
"""
from __future__ import annotations

import hashlib
from typing import Iterable

# ---------------------------------------------------------------- 主题令牌

GREEN_DARK: dict[str, str] = {
    "bg": "#0E1A16",
    "surface": "#14241F",
    "surface_2": "#1B302A",
    "border": "#24443B",
    "border_strong": "#33604F",
    "text_1": "#EAF4EF",
    "text_2": "#9DBCAF",
    "text_3": "#6F9184",
    "brand": "#1F6F63",
    "brand_bright": "#3E8E7E",
    "brand_soft": "#7FB3A7",
    "on_brand": "#FFFFFF",
    "success": "#5FC2A0",
    "warning": "#D4A574",
    "danger": "#D08068",
}

GREEN_LIGHT: dict[str, str] = {
    "bg": "#F5F7F6",
    "surface": "#FFFFFF",
    "surface_2": "#EDF1EF",
    "border": "#DFE5E2",
    "border_strong": "#C7D0CB",
    "text_1": "#16211E",
    "text_2": "#54615C",
    "text_3": "#6E7B75",
    "brand": "#1F6F63",
    "brand_bright": "#3E8E7E",
    "brand_soft": "#7FB3A7",
    "on_brand": "#FFFFFF",
    "success": "#2E8B68",
    "warning": "#B87A28",
    "danger": "#B84B4B",
}

THEMES = {"dark": GREEN_DARK, "light": GREEN_LIGHT}

# 热力图 5 级（低 → 高），始终走绿色系
HEAT_RAMP: tuple[str, ...] = (
    "#1B302A", "#265C4E", "#2E7C67", "#3E9E81", "#5FC2A0",
)

# ---------------------------------------------------------------- 品牌色

# 顺序即匹配优先级：长前缀放前面，避免 "gpt" 抢走 "gpt-4o-mini" 之外的误判
BRAND_COLORS: dict[str, str] = {
    "deepseek": "#4D6BFE",   # DeepSeek 蓝
    "claude": "#D97757",     # Anthropic 陶土橙
    "sonnet": "#D97757",
    "opus": "#D97757",
    "haiku": "#D97757",
    "gpt": "#10A37F",        # OpenAI 绿（与主题近，靠描边区分）
    "o1": "#10A37F",
    "o3": "#10A37F",
    "o4": "#10A37F",
    "codex": "#10A37F",
    "hunyuan": "#00A3B5",    # 腾讯混元青
    "hy": "#00A3B5",         # 用户日志里的 hy4-free / hy3
    "glm": "#3B6FE0",        # 智谱
    "qwen": "#7B5CFA",       # 通义千问
    "gemini": "#4285F4",     # Google
    "kimi": "#6B5BD2",       # 月之暗面
    "llama": "#0668E1",
    "mistral": "#FA520F",
    "grok": "#8A8F98",
    "auto": "#7FB3A7",       # 平台自动路由，归到绿色系弱色
}

BRAND_NAMES: dict[str, str] = {
    "deepseek": "DeepSeek", "claude": "Anthropic", "sonnet": "Anthropic",
    "opus": "Anthropic", "haiku": "Anthropic", "gpt": "OpenAI", "o1": "OpenAI",
    "o3": "OpenAI", "o4": "OpenAI", "codex": "OpenAI", "hunyuan": "腾讯混元",
    "hy": "腾讯混元", "glm": "智谱 GLM", "qwen": "通义千问",
    "gemini": "Google", "kimi": "月之暗面", "llama": "Meta",
    "mistral": "Mistral", "grok": "xAI", "auto": "自动路由",
}

# 未知模型不引入新色相，用绿色系的明度阶梯稳定分配
UNKNOWN_RAMP: tuple[str, ...] = ("#5FC2A0", "#9BD9C0", "#2E7C67", "#B8E6D5", "#7FB3A7")


def brand_of(model: str) -> tuple[str, str]:
    """返回 ``(厂商 key, 展示名)``；未识别时返回 ``("unknown", "其他")``。"""
    name = (model or "").strip().lower()
    for key in BRAND_COLORS:
        if name.startswith(key):
            return key, BRAND_NAMES.get(key, key)
    return "unknown", "其他"


def color_of(model: str) -> str:
    """返回模型对应的数据系列色。未知模型用绿色阶稳定散列，保证同模型同色。"""
    key, _ = brand_of(model)
    if key != "unknown":
        return BRAND_COLORS[key]
    digest = hashlib.sha256((model or "").encode("utf-8")).digest()
    return UNKNOWN_RAMP[digest[0] % len(UNKNOWN_RAMP)]


def vendor_of(model: str) -> str:
    """厂商展示名，用于图例分组。"""
    return brand_of(model)[1]


def series_palette(models: Iterable[str]) -> dict[str, str]:
    """为一组模型批量生成调色板，保持插入顺序。"""
    return {m: color_of(m) for m in models}


def _lighten(hex_color: str, amount: float) -> str:
    """把颜色向白色推移，用于同厂商多模型的明度区分。"""
    raw = hex_color.lstrip("#")
    channels = [int(raw[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(
        f"{min(255, round(c + (255 - c) * amount)):02X}" for c in channels
    )


def palette_for(models: Iterable[str]) -> dict[str, str]:
    """生成一组模型的实际调色板。

    同一厂商的多个模型拿到的品牌色相同，堆叠图里会撞色（本机日志里
    ``hy4-free`` / ``hy3`` 都是腾讯混元）。这里对同色的第 2、3… 个模型
    按明度阶梯提亮，既保留厂商色相，又让每个模型可区分。
    """
    result: dict[str, str] = {}
    used: dict[str, int] = {}
    for model in models:
        base = color_of(model)
        index = used.get(base, 0)
        used[base] = index + 1
        result[model] = _lighten(base, 0.18 * index) if index else base
    return result


def theme(name: str = "dark") -> dict[str, str]:
    """取主题令牌；未知名称回退深色，避免 KeyError 打断渲染。"""
    return THEMES.get(name, GREEN_DARK)

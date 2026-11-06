# -*- coding: utf-8 -*-
"""绿色系主题令牌 + 模型厂商品牌色映射。

设计约定（渲染层与设计稿共用，改动需同步 docs/DESIGN_TOKENS.md）：

* **绿色系只出现在 UI 框架**：背景、卡片、边框、文字、主按钮、热力色阶。
* **品牌色只出现在数据系列**：图表柱/线、图例点、模型徽标。
* 品牌色**必须同时带文字标签**，不能只靠颜色区分（WCAG 1.4.1）。
* 主题与品牌色是两层正交的令牌，互不覆盖；浅色主题的主强调色是
  荧光绿 ``#00E5A0``，深色主题（暗夜玻璃版）的主强调色是荧光黄绿
  ``#D4FF2B``，通过 CSS 变量在运行时切换。
"""
from __future__ import annotations

import hashlib
from typing import Iterable

# ---------------------------------------------------------------- 主题令牌
# 浅色版 = 设计稿「荧光绿微发光 · 白底」定稿；深色版 = 「暗夜玻璃」定稿。

GREEN_DARK: dict[str, str] = {
    "bg": "#0A0B0C",
    "surface": "#12181B",
    "surface_2": "#1D2629",
    "border": "#FFFFFF1F",        # 白 12% 细描边（玻璃质感）
    "border_strong": "#FFFFFF38",  # 白 22%
    "text_1": "#EAF4EE",
    "text_2": "#AECBBE",
    "text_3": "#82A997",
    "brand": "#D4FF2B",           # 荧光黄绿：仅选中态 / 关键数值 / 状态点
    "brand_bright": "#D4FF2B",
    "brand_soft": "#D4FF2B1F",    # 选中胶囊底色（12% 黄绿）
    "on_brand": "#101404",
    "success": "#D4FF2B",
    "warning": "#E2C07A",
    "danger": "#D08068",
}

GREEN_LIGHT: dict[str, str] = {
    "bg": "#FFFFFF",
    "surface": "#FFFFFF",
    "surface_2": "#EEF6F1",
    "border": "#CBE9D9",
    "border_strong": "#8CE3BE",
    "text_1": "#0C3B2C",
    "text_2": "#3E6B58",
    "text_3": "#4E7A68",
    "brand": "#00E5A0",           # 荧光绿：填充 / 徽标 / 选中态（白底上不做正文色）
    "brand_bright": "#075C42",    # 深绿：承担强调文字（白底对比度达标）
    "brand_soft": "#DDF8EB",
    "on_brand": "#063B2B",
    "success": "#075C42",
    "warning": "#8A6D12",
    "danger": "#B84B4B",
}

THEMES = {"dark": GREEN_DARK, "light": GREEN_LIGHT}

# 热力图 7 级（低 → 高），始终走绿色系；通过 --h0..--h6 注入 CSS，随主题切换。
HEAT_LIGHT: tuple[str, ...] = (
    "#F1F8F4", "#D8F1E4", "#B5E6CF", "#8CD9B8", "#5FC79C", "#2FAE7E", "#0B7A57",
)
HEAT_DARK: tuple[str, ...] = (
    "#1B2422", "#1E3A30", "#22574A", "#27775F", "#2F9C74", "#43C08C", "#6BE8A8",
)
HEATMAPS = {"light": HEAT_LIGHT, "dark": HEAT_DARK}
HEAT_RAMP = HEAT_LIGHT  # 向后兼容的默认引用

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
    "hunyuan": "#00E5A0",    # 腾讯混元 → 荧光绿（设计稿定稿；hy3 靠明度阶梯区分）
    "hy": "#00E5A0",         # 用户日志里的 hy4-free / hy3
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

# 同厂商同色撞色时的变暗阶梯（第 1 个同色模型、第 2 个、第 3 个…）。
# 白底看板上「变暗」比「提亮」更可读：hy4-free=#00E5A0、hy3≈#007250。
COLLIDE_SHADES: tuple[float, ...] = (0.0, 0.50, 0.68, 0.78, 0.85)


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


def _darken(hex_color: str, amount: float) -> str:
    """按比例压暗颜色，用于同厂商多模型的明度阶梯区分。"""
    raw = hex_color.lstrip("#")
    channels = [int(raw[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{max(0, round(c * (1 - amount))):02X}" for c in channels)


def palette_for(models: Iterable[str]) -> dict[str, str]:
    """生成一组模型的实际调色板。

    同一厂商的多个模型拿到的品牌色相同，堆叠图里会撞色（本机日志里
    ``hy4-free`` / ``hy3`` 都是腾讯混元）。这里对同色的第 2、3… 个模型
    按阶梯压暗，既保留厂商色相，又让每个模型可区分。
    """
    result: dict[str, str] = {}
    used: dict[str, int] = {}
    for model in models:
        base = color_of(model)
        index = used.get(base, 0)
        used[base] = index + 1
        shade = COLLIDE_SHADES[min(index, len(COLLIDE_SHADES) - 1)]
        result[model] = _darken(base, shade) if shade else base
    return result


def theme(name: str = "light") -> dict[str, str]:
    """取主题令牌；未知名称回退浅色，避免 KeyError 打断渲染。"""
    return THEMES.get(name, GREEN_LIGHT)

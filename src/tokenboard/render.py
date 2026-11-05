# -*- coding: utf-8 -*-
"""单文件离线 HTML 渲染。

设计约束（与 docs/DESIGN_TOKENS.md、Ardot 绿色版设计稿三方一致）：
  * UI 框架只用 :mod:`tokenboard.brands` 的绿色系令牌；
  * 品牌色只出现在数据系列，并且永远配文字标签；
  * 零外部请求、零第三方库，生成的 HTML 断网也能看。

模板用 ``str.replace`` 注入而不是 f-string，避免 CSS/JS 里大量花括号被误解释。
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Sequence

from .aggregate import Summary
from .brands import GREEN_DARK, GREEN_LIGHT, HEAT_RAMP, palette_for, vendor_of
from .models import SourceStatus, UsageRecord

_CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
background:var(--bg);color:var(--t1);padding:26px 20px 64px;max-width:1480px;margin:0 auto;
-webkit-font-smoothing:antialiased}
body[data-theme=dark]{__DARK__}
body[data-theme=light]{__LIGHT__}
h1{font-size:24px;font-weight:650;letter-spacing:.2px}
.sub{font-size:12px;color:var(--t3);margin-top:6px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;margin-bottom:20px;flex-wrap:wrap}
.hdr-tools{display:flex;gap:8px;align-items:center}
.btn{border:1px solid var(--bd);background:var(--card);color:var(--t2);font-size:12px;
padding:7px 14px;border-radius:8px;cursor:pointer}
.btn:hover{border-color:var(--bds);color:var(--t1)}
.btn.primary{background:var(--brand);border-color:var(--brand);color:#fff}
.hero{background:linear-gradient(100deg,var(--brand),#175B51);border-radius:14px;padding:22px 26px;
color:#fff;margin-bottom:18px;position:relative;overflow:hidden}
.hero .lab{font-size:10px;letter-spacing:.18em;color:#BFE4D9}
.hero .main{font-size:21px;font-weight:650;margin-top:9px;line-height:1.45}
.hero .sub2{font-size:12px;color:#CDE7E0;margin-top:8px}
.hero .warn{font-size:11px;color:#E2C07A;margin-top:12px}
.hero .side{position:absolute;right:26px;top:22px;text-align:right}
.hero .side .k{font-size:10px;color:#BFE4D9}
.hero .side .v{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:16px;font-weight:700;margin-top:4px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:22px}
.kpi{background:var(--card);border:1px solid var(--bd);border-radius:11px;padding:15px 16px}
.kpi .k{font-size:11px;color:var(--t3)}
.kpi .v{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:22px;font-weight:700;margin-top:8px;
font-variant-numeric:tabular-nums;white-space:nowrap}
.kpi .v small{font-size:12px;color:var(--t3);font-weight:500;margin-left:3px}
.kpi.emph{border-left:3px solid var(--brand)}
.kpi.emph .v{color:var(--brandb)}
.sec{font-size:13px;font-weight:650;margin:26px 0 12px;display:flex;align-items:baseline;gap:10px}
.sec b{font-family:ui-monospace,monospace;font-size:11px;color:var(--brandb);font-weight:700}
.sec span{font-size:11px;font-weight:400;color:var(--t3)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:900px){.grid{grid-template-columns:1fr}.hero .side{display:none}}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:18px 20px;margin-bottom:14px}
.card h2{font-size:14px;font-weight:600;margin-bottom:4px}
.card .cap{font-size:10.5px;color:var(--t3);margin-bottom:14px;line-height:1.5}
.row{display:flex;align-items:center;gap:10px;padding:7px 0;font-size:12px}
.row .nm{width:38%;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--t2)}
.row .bar{flex:1;height:9px;background:var(--surface2);border-radius:5px;overflow:hidden}
.row .bar i{display:block;height:100%;border-radius:5px}
.row .num{width:24%;text-align:right;font-family:ui-monospace,monospace;font-size:11px;
font-variant-numeric:tabular-nums;color:var(--t1);white-space:nowrap}
.dot{width:9px;height:9px;border-radius:3px;flex:none;border:1px solid rgba(0,0,0,.18)}
.vendor{font-size:9px;color:var(--t3);border:1px solid var(--bd);border-radius:4px;padding:1px 5px;flex:none}
table{width:100%;border-collapse:collapse;font-size:11.5px}
th{text-align:left;font-weight:500;color:var(--t3);font-size:10px;padding:7px 6px;border-bottom:1px solid var(--bd)}
td{padding:8px 6px;border-bottom:1px solid var(--bd);color:var(--t2)}
td.mono{font-family:ui-monospace,monospace;font-variant-numeric:tabular-nums;color:var(--t1)}
.pill{font-size:9.5px;padding:2px 7px;border-radius:999px;border:1px solid var(--bd)}
.pill.ok{color:var(--ok);border-color:var(--ok)}
.pill.no{color:var(--warn);border-color:var(--warn)}
.foot{margin-top:26px;padding-top:14px;border-top:1px solid var(--bd);font-size:10.5px;color:var(--t3);line-height:1.8}
svg{display:block;width:100%;height:auto}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:10px}
.legend span{font-size:10.5px;color:var(--t2);display:flex;align-items:center;gap:5px}
"""

_TEMPLATE = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>__CSS__</style></head>
<body data-theme="__THEME__">
<header><div><h1>__TITLE__</h1><div class="sub">__SUBTITLE__</div></div>
<div class="hdr-tools"><button class="btn" id="themeBtn">切换主题</button>
<button class="btn primary" onclick="window.print()">导出 PDF</button></div></header>
__HERO__
__KPIS__
<div class="sec"><b>01</b> 模型与平台 <span>数据系列使用厂商品牌色，UI 框架统一绿色系</span></div>
<div class="grid">
<div class="card"><h2>按模型消耗</h2><div class="cap">__MODELCAP__</div>__MODELS__</div>
<div class="card"><h2>按平台消耗</h2><div class="cap">已接入平台的请求级用量分布</div>__PLATFORMS__</div>
</div>
<div class="sec"><b>02</b> 时间节律 <span>热力色阶走绿色系，不引入新色相</span></div>
<div class="grid">
<div class="card"><h2>每日用量趋势</h2><div class="cap">按模型堆叠 · 最新在右 · 单位 Token</div>__DAILY__</div>
<div class="card"><h2>24 小时活跃分布</h2><div class="cap">按小时聚合 · 色深代表消耗强度</div>__HEAT__
<div class="cap" style="margin:12px 0 0">__BANDS__</div></div>
</div>
<div class="sec"><b>03</b> 工作空间与数据源 <span>下钻顺序：平台 → 工作空间 → 会话 → 请求</span></div>
<div class="grid">
<div class="card"><h2>工作空间</h2><div class="cap">按消耗排序，最多显示 10 个</div>__WORKSPACES__</div>
<div class="card"><h2>数据源状态</h2><div class="cap">未验证平台不会伪装成已支持；请用 --path 指定真实日志目录</div>__SOURCES__</div>
</div>
<div class="foot">__FOOTER__</div>
<script>__SCRIPT__</script></body></html>"""

_SCRIPT = r"""
(function(){
  var b=document.body,btn=document.getElementById('themeBtn');
  try{var t=localStorage.getItem('tb-theme');if(t==='light'||t==='dark')b.dataset.theme=t;}catch(e){}
  function label(){btn.textContent=b.dataset.theme==='dark'?'浅色':'深色';}
  label();
  btn.onclick=function(){b.dataset.theme=(b.dataset.theme==='dark'?'light':'dark');
    try{localStorage.setItem('tb-theme',b.dataset.theme);}catch(e){} label();};
})();
"""


def _vars(tokens: dict[str, str]) -> str:
    """把主题令牌转成 CSS 自定义属性声明。"""
    mapping = {
        "bg": "--bg", "surface": "--card", "surface_2": "--surface2",
        "border": "--bd", "border_strong": "--bds", "text_1": "--t1",
        "text_2": "--t2", "text_3": "--t3", "brand": "--brand",
        "brand_bright": "--brandb", "success": "--ok", "warning": "--warn",
        "danger": "--danger",
    }
    return "".join(f"{css}:{tokens[key]};" for key, css in mapping.items() if key in tokens)


def e(value: Any) -> str:
    """HTML 转义；工作空间名、模型名可能来自不可信的日志内容。"""
    return html.escape(str(value), quote=True)


def fmt(value: float | int) -> str:
    """中文习惯的数字缩写：万 / 亿。"""
    value = float(value)
    if value >= 1e8:
        return f"{value / 1e8:.2f} 亿"
    if value >= 1e4:
        return f"{value / 1e4:.1f} 万"
    return f"{int(round(value)):,}"


def _bar_rows(items: Sequence[tuple[str, float, str, str]], cap: float, unit: str = "") -> str:
    """生成横向条形列表。items = (名称, 数值, 颜色, 附加标签)"""
    if not items:
        return '<div class="cap">暂无数据</div>'
    rows = []
    for name, value, color, extra in items:
        pct = (value / cap * 100) if cap else 0
        rows.append(
            f'<div class="row"><span class="dot" style="background:{e(color)}"></span>'
            f'<span class="nm" title="{e(name)}">{e(name)}</span>'
            f'<span class="bar"><i style="width:{pct:.1f}%;background:{e(color)}"></i></span>'
            f'<span class="num">{fmt(value)}{unit}</span>{extra}</div>'
        )
    return "".join(rows)


def _daily_svg(records: Iterable[UsageRecord], summary: Summary) -> str:
    """按天 × 模型堆叠柱；品牌色只出现在这里的数据系列上。"""
    palette = palette_for(summary.models)
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for rec in records:
        day = datetime.fromtimestamp(rec.ts).strftime("%Y-%m-%d")
        matrix[day][rec.model] += rec.total_tokens
    days = sorted(matrix)[-30:]
    if not days:
        return '<div class="cap">暂无数据</div>'
    max_total = max(sum(matrix[d].values()) for d in days) or 1
    width, height, left, base = 700, 200, 46, 168
    slot = (width - left - 10) / len(days)
    bar_w = max(4.0, min(38.0, slot * 0.62))
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="每日模型用量堆叠柱图">',
        f'<path d="M{left} 20H{width - 6}M{left} 94H{width - 6}M{left} {base}H{width - 6}" '
        'stroke="var(--bd)" stroke-width="1" fill="none"/>',
        f'<text x="4" y="24" fill="var(--t3)" font-size="9">{fmt(max_total)}</text>',
        f'<text x="4" y="{base + 3}" fill="var(--t3)" font-size="9">0</text>',
    ]
    for i, day in enumerate(days):
        x = left + i * slot + (slot - bar_w) / 2
        acc = 0
        for model in summary.models:
            value = matrix[day].get(model, 0)
            if not value:
                continue
            h = value / max_total * (base - 20)
            y = base - acc - h
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(1, h):.1f}" '
                f'fill="{e(palette[model])}" stroke="var(--bg)" stroke-width=".6">'
                f'<title>{e(day)} · {e(model)} · {fmt(value)}</title></rect>'
            )
            acc += h
        if len(days) <= 8 or i % max(1, len(days) // 6) == 0:
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{base + 16}" fill="var(--t3)" '
                f'font-size="9" text-anchor="middle">{e(day[5:])}</text>'
            )
    parts.append("</svg>")
    legend = "".join(
        f'<span><i class="dot" style="background:{e(palette[m])}"></i>{e(m)} · {e(vendor_of(m))}</span>'
        for m in summary.models[:8]
    )
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def _heat_svg(summary: Summary) -> str:
    """24 小时热力条，五级绿色阶。"""
    peak = max(summary.hourly) or 1
    width, cell, gap = 700, 26, 3
    parts = ['<svg viewBox="0 0 700 44" role="img" aria-label="24 小时活跃热力图">']
    for hour, value in enumerate(summary.hourly):
        level = 0 if value == 0 else min(4, 1 + int(value / peak * 3.999))
        color = HEAT_RAMP[level]
        x = hour * (cell + gap)
        parts.append(
            f'<rect x="{x}" y="4" width="{cell}" height="20" rx="3" fill="{color}">'
            f'<title>{hour}:00 · {fmt(value)}</title></rect>'
        )
        if hour % 4 == 0:
            parts.append(f'<text x="{x}" y="38" fill="var(--t3)" font-size="9">{hour}</text>')
    parts.append("</svg>")
    return "".join(parts)


def render_html(
    summary: Summary,
    records: Sequence[UsageRecord],
    statuses: Sequence[SourceStatus] = (),
    *,
    theme_name: str = "dark",
    title: str = "TokenBoard · 多平台消耗洞察",
    generated: str | None = None,
    window_note: str = "",
) -> str:
    """渲染完整的单文件 HTML；不访问网络、不写文件。"""
    generated = generated or datetime.now().strftime("%Y-%m-%d %H:%M")
    kpi = summary.kpi()
    models = summary.models
    palette = palette_for(models)
    model_rows = [
        (m, summary.by_model[m]["tokens"], palette[m],
         f'<span class="vendor">{e(vendor_of(m))}</span>')
        for m in models[:10]
    ]
    cap_model = max((v for _, v, _, _ in model_rows), default=1)
    platform_rows = [
        (p, summary.by_platform[p]["tokens"], "#1F6F63", "") for p in summary.platforms
    ]
    cap_platform = max((v for _, v, _, _ in platform_rows), default=1)
    ws_rows = [
        (w, summary.by_workspace[w]["tokens"], "#3E8E7E", "")
        for w in sorted(summary.by_workspace, key=lambda x: -summary.by_workspace[x]["tokens"])[:10]
    ]
    cap_ws = max((v for _, v, _, _ in ws_rows), default=1)

    # 结论层：一句话讲清「花了多少、命中多少、花在哪」
    top_model = models[0] if models else "—"
    top_share = (
        summary.by_model[top_model]["tokens"] / summary.total_tokens * 100
        if summary.total_tokens else 0
    )
    hero = (
        '<div class="hero"><div class="lab">本 期 结 论</div>'
        f'<div class="main">{fmt(summary.total_tokens)} Token · {kpi["requests"]:,} 次请求 · '
        f'预估 ¥{kpi["estimated_cost_cny"]:.2f}</div>'
        f'<div class="sub2">缓存命中 {kpi["cache_hit_rate"]:.1f}% · '
        f'主力模型 {e(top_model)} 占 {top_share:.1f}% · '
        f'覆盖 {len(summary.platforms)} 个平台 / {kpi["active_days"]} 个有数据日</div>'
        + (f'<div class="warn">{e(window_note)}</div>' if window_note else "")
        + f'<div class="side"><div class="k">折合单价</div>'
          f'<div class="v">¥{kpi["price_per_million_cny"]:.2f} / 百万</div></div></div>'
    )

    kpi_items = [
        ("合计 Token", fmt(summary.total_tokens), "", True),
        ("日均（有数据日）", fmt(summary.daily_average), "", False),
        ("请求轮次", f'{kpi["requests"]:,}', "", False),
        ("会话", f'{kpi["sessions"]:,}', "", False),
        ("输入 / 输出比", f'{kpi["input_output_ratio"]:.1f} : 1', "", False),
        ("缓存命中率", f'{kpi["cache_hit_rate"]:.1f}', "%", False),
        ("预估金额", f'¥{kpi["estimated_cost_cny"]:.2f}', "", False),
    ]
    kpi_parts = ['<div class="kpis">']
    for label, value, unit, emph in kpi_items:
        # 拆开写，避免嵌套 f-string 在 Python 3.10/3.11 上语法不兼容
        suffix = f"<small>{e(unit)}</small>" if unit else ""
        cls = "kpi emph" if emph else "kpi"
        kpi_parts.append(
            f'<div class="{cls}"><div class="k">{e(label)}</div>'
            f'<div class="v">{e(value)}{suffix}</div></div>'
        )
    kpi_parts.append("</div>")
    kpis = "".join(kpi_parts)

    band_total = sum(summary.bands) or 1
    band_names = ("凌晨 0–6", "上午 6–12", "下午 12–18", "晚间 18–24")
    bands = " · ".join(
        f"{n} {v / band_total * 100:.1f}%" for n, v in zip(band_names, summary.bands)
    )

    source_rows = []
    for s in statuses:
        pill = '<span class="pill ok">已验证</span>' if s.verified else '<span class="pill no">未验证</span>'
        source_rows.append(
            f'<tr><td>{e(s.display_name)}</td><td class="mono">{s.file_count}</td>'
            f'<td>{pill}</td><td title="{e(s.note)}">{e(s.note[:38])}</td></tr>'
        )
    sources = (
        "<table><thead><tr><th>平台</th><th>日志文件</th><th>状态</th><th>说明</th></tr></thead><tbody>"
        + ("".join(source_rows) or '<tr><td colspan="4">未指定数据源</td></tr>')
        + "</tbody></table>"
    )

    footer = (
        f"生成时间 {e(generated)} · 数据来自本机会话日志，不外发、无外部依赖<br>"
        "口径：请求级真实 usage；金额按牌价估算，缓存读命中走缓存价、缓存写入按输入价 ×1.25、"
        "其余输入走输入价，输出走输出价。不同套餐单价请用 --prices 覆盖。<br>"
        "绿色系用于 UI 框架，厂商品牌色仅用于数据系列且始终附文字标签（WCAG 1.4.1）。"
        "未验证平台只表示「本机没有真实日志可供核对」，不代表功能已支持。"
    )
    subtitle = (
        f"请求级真实 usage · 绿色系统一主题 · 模型品牌色数据系列 · 数据截至 {e(generated)}"
    )

    css = (
        _CSS.replace("__DARK__", _vars(GREEN_DARK))
        .replace("__LIGHT__", _vars(GREEN_LIGHT))
    )
    replacements = {
        "__TITLE__": e(title),
        "__SUBTITLE__": subtitle,
        "__THEME__": "light" if theme_name == "light" else "dark",
        "__CSS__": css,
        "__HERO__": hero,
        "__KPIS__": kpis,
        "__MODELCAP__": "按厂商品牌色区分；同时保留文字标签，不依赖颜色单独传达信息",
        "__MODELS__": _bar_rows(model_rows, cap_model),
        "__PLATFORMS__": _bar_rows(platform_rows, cap_platform),
        "__DAILY__": _daily_svg(records, summary),
        "__HEAT__": _heat_svg(summary),
        "__BANDS__": bands,
        "__WORKSPACES__": _bar_rows(ws_rows, cap_ws),
        "__SOURCES__": sources,
        "__FOOTER__": footer,
        "__SCRIPT__": _SCRIPT,
    }
    output = _TEMPLATE
    for key, value in replacements.items():
        output = output.replace(key, value)
    return output


def summary_json(summary: Summary, statuses: Sequence[SourceStatus] = ()) -> str:
    """供 MCP / CLI --format json 使用的稳定 JSON 结构。"""
    payload = summary.to_dict()
    payload["sources"] = [s.to_dict() for s in statuses]
    return json.dumps(payload, ensure_ascii=False, indent=2)

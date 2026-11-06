# -*- coding: utf-8 -*-
"""单文件离线 HTML 渲染。

设计约束（与 docs/DESIGN_TOKENS.md、Ardot 定稿设计稿三方一致）：
  * UI 框架只用 :mod:`tokenboard.brands` 的绿色系令牌；
  * 品牌色只出现在数据系列，并且永远配文字标签；
  * 零外部请求、零第三方库，生成的 HTML 断网也能看；
  * 浅色为默认主题（白底荧光绿），深色为「暗夜玻璃」变体，运行时切换。

模板用 ``str.replace`` 注入而不是 f-string，避免 CSS/JS 里大量花括号被误解释。
"""
from __future__ import annotations

import html
import json
import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable, Sequence

from .aggregate import Summary
from .brands import GREEN_DARK, GREEN_LIGHT, HEATMAPS, palette_for, vendor_of
from .models import SourceStatus, UsageRecord

_SANS = '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif'
_MONO = 'ui-monospace,"JetBrains Mono",SFMono-Regular,Menlo,Consolas,monospace'

_CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
:root{--sans:__SANS__;--mono:__MONO__}
body{font-family:var(--sans);background:var(--bg);color:var(--t1);padding:24px 26px 56px;
max-width:1560px;margin:0 auto;-webkit-font-smoothing:antialiased}
body[data-theme=light]{__LIGHT__ __HEAT_L__}
body[data-theme=dark]{__DARK__ __HEAT_D__;
background:radial-gradient(1100px 520px at 50% -8%,#1A201C 0%,var(--bg) 62%) fixed}
/* ---- 顶栏 ---- */
.crumbrow{display:flex;justify-content:space-between;align-items:center;font-size:11px;color:var(--t3)}
.titlerow{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;flex-wrap:wrap;margin:14px 0 20px}
h1{font-size:28px;font-weight:700;letter-spacing:.2px}
.sub{font-size:11.5px;color:var(--t3);margin-top:6px}
.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.chip{border:1px solid var(--bd);background:var(--surface);color:var(--t2);font-size:10.5px;
padding:6px 12px;border-radius:999px;cursor:pointer;font-family:var(--sans)}
.chip:hover{border-color:var(--bds);color:var(--t1)}
.twin{display:flex;border:1px solid var(--bd);border-radius:10px;background:var(--surface);padding:3px;gap:2px}
.twin span{font-size:11px;color:var(--t2);padding:5px 13px;border-radius:7px;white-space:nowrap}
.twin span.on{background:var(--brandsoft);color:var(--brandb);font-weight:600;
box-shadow:inset 0 0 0 1px var(--brand)}
/* ---- 结论条 ---- */
.hero{position:relative;background:var(--surface);border:1px solid var(--bds);border-radius:20px;
padding:20px 26px 18px;margin-bottom:16px;overflow:hidden}
.hero:before{content:"";position:absolute;left:0;top:20px;bottom:20px;width:3px;
border-radius:2px;background:var(--brand)}
.hero .lab{font-size:10px;letter-spacing:.18em;color:var(--t2)}
.hero .main{font-size:28px;font-weight:700;margin-top:8px;line-height:1.35;font-variant-numeric:tabular-nums}
.hero .sub2{font-size:11.5px;color:var(--t2);margin-top:8px}
.hero .warn{font-size:10.5px;color:var(--warn);margin-top:12px}
.hero .side{position:absolute;right:26px;top:30px;text-align:right}
.hero .side .k{font-size:10px;color:var(--t2)}
.hero .side .v{font-family:var(--mono);font-size:18px;font-weight:700;margin-top:5px}
/* ---- KPI ---- */
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:8px}
.kpis.three{grid-template-columns:repeat(3,1fr)}
.kpi{background:var(--surface);border:1px solid var(--bd);border-radius:20px;padding:16px 18px}
.kpi .k{font-size:11px;color:var(--t3)}
.kpi .v{font-family:var(--mono);font-size:32px;font-weight:700;margin-top:10px;line-height:1.1;
font-variant-numeric:tabular-nums;white-space:nowrap}
.kpi .v small{font-size:13px;color:var(--t3);font-weight:500;margin-left:4px}
.kpi.emph .v{color:var(--brandb)}
/* ---- 分区 ---- */
.sec{display:flex;align-items:baseline;gap:12px;margin:26px 0 10px;padding-bottom:10px;
border-bottom:1px solid var(--bd)}
.sec b{font-family:var(--mono);font-size:11px;color:var(--brandb);font-weight:700}
.sec h2{font-size:14px;font-weight:650}
.sec span{font-size:10.5px;font-weight:400;color:var(--t3);margin-left:auto}
.card{position:relative;background:var(--surface);border:1px solid var(--bd);border-radius:20px;
padding:18px 22px;margin-bottom:16px}
.card h3{font-size:14px;font-weight:650}
.card .cap{font-size:10.5px;color:var(--t3);margin-top:5px;line-height:1.6}
.hdnote{font-size:10.5px;color:var(--t3)}
.duo{display:grid;grid-template-columns:2fr 1fr;gap:16px}
@media(max-width:980px){.duo{grid-template-columns:1fr}
.kpis,.kpis.three{grid-template-columns:repeat(2,1fr)}.chips{grid-template-columns:repeat(2,1fr)}}
/* ---- 模型条 ---- */
.mrow{display:grid;grid-template-columns:200px 1fr 300px;gap:12px;align-items:center;
padding:9px 0;font-size:11.5px}
.mrow .nm{font-family:var(--mono);font-weight:600;color:var(--t1);overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.mrow .nm.sans{font-family:var(--sans);font-weight:500}
.mrow .track{height:12px;background:var(--surface2);border-radius:8px;overflow:hidden}
.mrow .track i{display:block;height:100%;border-radius:8px}
.mrow .num{font-family:var(--mono);font-size:10.5px;color:var(--t2);text-align:right;
font-variant-numeric:tabular-nums;white-space:nowrap}
.dot{width:9px;height:9px;border-radius:3px;flex:none;display:inline-block;vertical-align:-1px}
.vendor{font-size:9px;color:var(--t3);border:1px solid var(--bd);border-radius:4px;
padding:1px 5px;margin-left:6px}
/* ---- 通用表 ---- */
table{width:100%;border-collapse:collapse;font-size:11.5px}
th{text-align:left;font-weight:500;color:var(--t3);font-size:10px;padding:8px 8px;
border-bottom:1px solid var(--bd)}
td{padding:10px 8px;border-bottom:1px solid var(--bd);color:var(--t2)}
tbody tr:last-child td{border-bottom:none}
td.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
td.num{font-family:var(--mono);color:var(--t1);font-weight:600}
tr.total td{border-top:1px solid var(--bds);border-bottom:none;color:var(--t1);font-weight:600}
.pill{font-size:9.5px;padding:2px 8px;border-radius:999px;border:1px solid var(--bd)}
.pill.ok{color:var(--ok);border-color:var(--ok)}
.pill.no{color:var(--warn);border-color:var(--warn)}
.livedot{width:8px;height:8px;border-radius:50%;background:var(--brand);display:inline-block;margin-right:6px}
/* ---- 工作空间卡 ---- */
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0 4px}
.toolbar .spacer{flex:1}
.mini{border:1px solid var(--bd);background:var(--surface);color:var(--t2);font-size:10px;
padding:5px 11px;border-radius:7px;cursor:pointer;font-family:var(--sans)}
.mini.on{background:var(--brandsoft);border-color:var(--brand);color:var(--brandb);font-weight:600}
.mini:hover{border-color:var(--bds)}
.wssearch{border:1px solid var(--bd);background:var(--surface);color:var(--t1);font-size:10.5px;
padding:5px 10px;border-radius:7px;width:130px;outline:none;font-family:var(--sans)}
.wssearch:focus{border-color:var(--bds)}
.wshead{display:grid;grid-template-columns:200px 120px 150px 1fr 24px;gap:12px;
font-size:10px;color:var(--t3);padding:8px 0;border-bottom:1px solid var(--bd)}
.wsrow{display:grid;grid-template-columns:200px 120px 150px 1fr 24px;gap:12px;align-items:center;
padding:9px 0;border-bottom:1px solid var(--bd);font-size:10.5px}
.wsrow:last-child{border-bottom:none}
.wsrow .nm{font-family:var(--mono);color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wsrow .tk{font-family:var(--mono);color:var(--t1);font-variant-numeric:tabular-nums}
.wsrow .sh{color:var(--brandb);font-family:var(--mono)}
.wsrow .sh small{color:var(--t3);margin-left:4px}
.spark{display:flex;align-items:center;height:8px}
.spark i{height:8px;border-radius:2px;background:var(--brand);opacity:.85;margin-right:2px}
.spark i.alt{background:var(--brandb)}
/* ---- 指标切换（按 Token / 按金额） ---- */
.seg{display:inline-flex;border:1px solid var(--bd);border-radius:10px;background:var(--surface);
padding:3px;gap:2px}
.seg button{border:none;background:transparent;color:var(--t2);font-size:10px;padding:5px 13px;
border-radius:7px;cursor:pointer;font-family:var(--sans)}
.seg button.on{background:var(--brandsoft);color:var(--brandb);font-weight:600;
box-shadow:inset 0 0 0 1px var(--brand)}
.v-cost{display:none}
body[data-metric=cost] .v-cost{display:inline}
body[data-metric=cost] .v-token{display:none}
/* ---- 图表通用 ---- */
svg{display:block;width:100%;height:auto}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:8px}
.legend span{font-size:10.5px;color:var(--t2);display:flex;align-items:center;gap:6px}
.legend i{width:10px;height:10px;border-radius:3px;display:inline-block}
.distwrap{display:grid;grid-template-columns:340px 1fr;gap:22px;align-items:start}
@media(max-width:980px){.distwrap{grid-template-columns:1fr}}
.drow{display:grid;grid-template-columns:76px 48px 1fr 1fr;gap:10px;align-items:center;
padding:10px 0;border-bottom:1px solid var(--bd);font-size:11px}
.drow:last-child{border-bottom:none}
.dhead{font-size:10px;color:var(--t3);padding:0 0 2px}
.drow .nm{font-family:var(--mono);font-weight:600;color:var(--t1)}
.drow .val{font-family:var(--mono);font-weight:700;color:var(--t1);font-variant-numeric:tabular-nums}
.drow .val small{display:block;font-weight:400;font-size:9px;color:var(--t3);margin-top:4px}
.drow .val small i{display:block;height:5px;border-radius:2.5px;margin-top:2px}
/* ---- 日活热力 ---- */
.chips{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:12px 0 14px}
.chip2{border:1px solid var(--bd);border-radius:9px;padding:10px 14px;display:flex;
justify-content:space-between;align-items:center;font-size:10.5px;color:var(--t2)}
.chip2 b{font-family:var(--mono);font-size:15px;font-weight:700;color:var(--t1)}
.hmlegend{display:flex;align-items:center;gap:7px;font-size:10px;color:var(--t3);margin-bottom:6px}
.hmlegend i{width:12px;height:12px;border-radius:3px;display:inline-block}
.foot{margin-top:28px;padding-top:14px;border-top:1px solid var(--bd);font-size:10.5px;
color:var(--t3);line-height:1.9}
"""

_TEMPLATE = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>__CSS__</style></head>
<body data-theme="__THEME__" data-metric="token">
<div class="crumbrow"><span>总览&ensp;/&ensp;消耗洞察</span>
<span>数据截至 __GENERATED__ · 离线可用</span></div>
<div class="titlerow"><div><h1>__TITLE__</h1><div class="sub">__SUBTITLE__</div></div>
<div class="controls">
<div class="twin">__PERIODS__</div>
<button class="chip" id="themeBtn">深色</button>
<button class="chip" onclick="window.print()">导出 PDF</button></div></div>
__HERO__
<div class="kpis">__KPIS__</div>
<div class="sec"><b>01</b><h2>补充指标 · 原统计口径</h2><span>__S1NOTE__</span></div>
<div class="kpis three">__KPI2__</div>
<div class="sec"><b>02</b><h2>模型与品牌色</h2><span>同厂商模型用明度阶梯区分，色相保持品牌体系</span></div>
<div class="duo">
<div class="card"><h3>按模型消耗</h3><div class="cap">__MODELCAP__</div>__MODELS__</div>
<div class="card"><h3>每日用量趋势</h3><div class="cap">按模型堆叠 · 最新在右 · 单位 Token</div>__DAILY__</div>
</div>
<div class="sec"><b>03</b><h2>数据源状态与口径</h2><span>下钻顺序：平台 → 工作空间 → 会话 → 请求</span></div>
<div class="card">__SOURCES__</div>
<div class="sec"><b>04</b><h2>使用分布与时间节律</h2><span>工作空间 / 请求规模 / 日活 / 时段 / 模型构成</span></div>
__DISTRIBUTION__
<div class="foot">__FOOTER__</div>
<script>__SCRIPT__</script></body></html>"""

_SCRIPT = r"""
(function(){
  var b=document.body;
  var btn=document.getElementById('themeBtn');
  try{var t=localStorage.getItem('tb-theme');if(t==='light'||t==='dark')b.dataset.theme=t;}catch(e){}
  function label(){btn.textContent=b.dataset.theme==='dark'?'浅色':'深色';}
  label();
  btn.onclick=function(){b.dataset.theme=(b.dataset.theme==='dark'?'light':'dark');
    try{localStorage.setItem('tb-theme',b.dataset.theme);}catch(e){} label();};
  var seg=document.getElementById('metricSeg');
  if(seg){seg.addEventListener('click',function(ev){
    var opt=ev.target.closest('[data-metric-opt]');if(!opt)return;
    b.dataset.metric=opt.getAttribute('data-metric-opt');
    [].forEach.call(seg.querySelectorAll('[data-metric-opt]'),function(x){
      x.classList.toggle('on',x===opt);});
  });}
  var list=document.getElementById('wsRows');
  if(list){
    function sortRows(by){var rows=[].slice.call(list.children);
      rows.sort(function(x,y){return (+y.dataset[by])-(+x.dataset[by]);});
      rows.forEach(function(r){list.appendChild(r);});}
    var st=document.getElementById('wsSortTok'),ss=document.getElementById('wsSortSes');
    if(st)st.onclick=function(){st.classList.add('on');if(ss)ss.classList.remove('on');sortRows('tokens');};
    if(ss)ss.onclick=function(){ss.classList.add('on');if(st)st.classList.remove('on');sortRows('sessions');};
    var q=document.getElementById('wsSearch');
    if(q)q.addEventListener('input',function(){var v=q.value.trim().toLowerCase();
      [].forEach.call(list.children,function(r){
        r.style.display=(!v||r.getAttribute('data-name').indexOf(v)>=0)?'':'none';});});
  }
})();
"""


# ------------------------------------------------------------------ 工具

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


def _nice_max(value: float) -> float:
    """把纵轴上限归整到 1/2/2.5/5 × 10^n，网格线读起来是整数。"""
    if value <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(value))
    for factor in (1, 2, 2.5, 5, 10):
        if value <= factor * mag:
            return factor * mag
    return 10 * mag


def _smooth_path(points: list[tuple[float, float]]) -> str:
    """Catmull-Rom → 三次贝塞尔，把离散序列变成设计稿里的平滑曲线。"""
    if not points:
        return ""
    if len(points) < 3:
        return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points)
    d = f"M{points[0][0]:.1f},{points[0][1]:.1f}"
    for i in range(len(points) - 1):
        p0 = points[i - 1] if i > 0 else points[0]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < len(points) else points[-1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        d += (f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f}"
              f" {p2[0]:.1f},{p2[1]:.1f}")
    return d


def _blend(hex_color: str, other: str, t: float) -> str:
    """两色插值；用于 90% 对比条的浅色变体。"""
    raw1, raw2 = hex_color.lstrip("#"), other.lstrip("#")
    out = []
    for i in (0, 2, 4):
        a, b = int(raw1[i:i + 2], 16), int(raw2[i:i + 2], 16)
        out.append(round(a + (b - a) * t))
    return "#" + "".join(f"{max(0, min(255, v)):02X}" for v in out)


def _vars(tokens: dict[str, str]) -> str:
    """把主题令牌转成 CSS 自定义属性声明。"""
    mapping = {
        "bg": "--bg", "surface": "--surface", "surface_2": "--surface2",
        "border": "--bd", "border_strong": "--bds", "text_1": "--t1",
        "text_2": "--t2", "text_3": "--t3", "brand": "--brand",
        "brand_bright": "--brandb", "brand_soft": "--brandsoft",
        "on_brand": "--onbrand", "success": "--ok", "warning": "--warn",
        "danger": "--danger",
    }
    return "".join(f"{css}:{tokens[key]};" for key, css in mapping.items() if key in tokens)


def _heat_vars(name: str) -> str:
    return "".join(f"--h{i}:{c};" for i, c in enumerate(HEATMAPS.get(name, HEATMAPS["light"])))


# ------------------------------------------------------------------ 区块

def _hero(summary: Summary, window_note: str) -> str:
    kpi = summary.kpi()
    top_model = summary.models[0] if summary.models else "—"
    top_share = (
        summary.by_model[top_model]["tokens"] / summary.total_tokens * 100
        if summary.total_tokens and summary.models else 0.0
    )
    warn = f'<div class="warn">{e(window_note)}</div>' if window_note else ""
    return (
        '<div class="hero"><div class="lab">本 期 结 论</div>'
        f'<div class="main">{fmt(summary.total_tokens)} Token&ensp;·&ensp;'
        f'{kpi["requests"]:,} 次请求&ensp;·&ensp;预估 ¥{kpi["estimated_cost_cny"]:.2f}</div>'
        f'<div class="sub2">缓存命中 {kpi["cache_hit_rate"]:.1f}%&ensp;·&ensp;'
        f'主力模型 {e(top_model)} 占 {top_share:.1f}%&ensp;·&ensp;'
        f'覆盖 {len(summary.by_platform)} 个平台 / {kpi["active_days"]} 个有数据日</div>{warn}'
        f'<div class="side"><div class="k">折合单价</div>'
        f'<div class="v">¥{kpi["price_per_million_cny"]:.2f} / 百万</div></div></div>'
    )


def _kpi_cards(items: Sequence[tuple[str, str, str, bool]]) -> str:
    parts = []
    for label_, value, unit, emph in items:
        suffix = f"<small>{e(unit)}</small>" if unit else ""
        cls = "kpi emph" if emph else "kpi"
        parts.append(
            f'<div class="{cls}"><div class="k">{e(label_)}</div>'
            f'<div class="v">{e(value)}{suffix}</div></div>'
        )
    return "".join(parts)


def _model_card(summary: Summary, palette: dict[str, str]) -> str:
    """按模型消耗：条形 + 两行口径（缓存命中 / 输入输出比），空轨道仅示意。"""
    if not summary.models:
        return '<div class="cap">暂无数据</div>'
    cap = max(summary.by_model[m]["tokens"] for m in summary.models[:8]) or 1
    rows = []
    for m in summary.models[:8]:
        tokens = summary.by_model[m]["tokens"]
        share = tokens / summary.total_tokens * 100 if summary.total_tokens else 0
        rows.append(
            f'<div class="mrow"><span class="nm"><i class="dot" style="background:{e(palette[m])}"></i>'
            f'{e(m)}<span class="vendor">{e(vendor_of(m))}</span></span>'
            f'<span class="track"><i style="width:{tokens / cap * 100:.1f}%;'
            f'background:{e(palette[m])}"></i></span>'
            f'<span class="num">{fmt(tokens)}&ensp;·&ensp;{e(vendor_of(m))}&ensp;·&ensp;'
            f'{share:.1f}%</span></div>'
        )
    metric_rows = (
        '<div class="mrow"><span class="nm sans">缓存命中率</span><span class="track"></span>'
        f'<span class="num">{summary.cache_hit_rate:.1f}%&ensp;·&ensp;缓存写入按 1.25× 输入价</span></div>'
        '<div class="mrow"><span class="nm sans">输入 / 输出比</span><span class="track"></span>'
        f'<span class="num">{summary.io_ratio:.1f} : 1&ensp;·&ensp;全局 50% {fmt(summary.global_p50)}</span></div>'
    )
    return "".join(rows) + metric_rows


def _daily_card(records: Iterable[UsageRecord], summary: Summary, palette: dict[str, str]) -> str:
    """按天 × 模型堆叠柱；品牌色只出现在这里的数据系列上。"""
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for rec in records:
        day = datetime.fromtimestamp(rec.ts).strftime("%Y-%m-%d")
        matrix[day][rec.model] += rec.total_tokens
    days = sorted(matrix)[-14:]
    if not days:
        return '<div class="cap">暂无数据</div>'
    max_total = max(sum(matrix[d].values()) for d in days) or 1
    width, height, left, base = 460, 190, 40, 158
    slot = (width - left - 8) / len(days)
    bar_w = max(5.0, min(34.0, slot * 0.6))
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="每日模型用量堆叠柱图">',
        f'<path d="M{left} 16H{width - 4}M{left} {base}H{width - 4}" '
        'stroke="var(--bd)" stroke-width="1" fill="none"/>',
        f'<text x="2" y="20" fill="var(--t3)" font-size="9">{fmt(max_total)}</text>',
        f'<text x="2" y="{base + 3}" fill="var(--t3)" font-size="9">0</text>',
    ]
    for i, day in enumerate(days):
        x = left + i * slot + (slot - bar_w) / 2
        acc = 0.0
        for model in summary.models:
            value = matrix[day].get(model, 0)
            if not value:
                continue
            h = value / max_total * (base - 16)
            y = base - acc - h
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(1, h):.1f}" '
                f'fill="{e(palette[model])}" stroke="var(--bg)" stroke-width=".6">'
                f'<title>{e(day)} · {e(model)} · {fmt(value)}</title></rect>'
            )
            acc += h
        step = max(1, len(days) // 3)
        if len(days) <= 4 or i % step == 0:
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{base + 15}" fill="var(--t3)" '
                f'font-size="9" text-anchor="middle">{e(day[5:])}</text>'
            )
    parts.append("</svg>")
    legend = "".join(
        f'<span><i style="background:{e(palette[m])}"></i>{e(m)}</span>'
        for m in summary.models[:6]
    )
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def _sources_card(statuses: Sequence[SourceStatus]) -> str:
    rows = []
    for s in statuses:
        pill = ('<span class="pill ok">已验证</span>' if s.verified
                else '<span class="pill no">未验证</span>')
        note = e(s.note) if s.note else ("" if s.verified else "本机没有真实日志可供核对")
        root = e(s.roots[0]) if s.roots else "—"
        rows.append(
            f'<tr><td style="color:var(--t1);font-weight:600">{e(s.display_name)}</td>'
            f'<td class="mono">{root}</td><td class="mono">{s.file_count}</td>'
            f'<td>{pill}</td><td style="font-size:10.5px">{note}</td></tr>'
        )
    live = ('<span class="livedot"></span><span style="font-size:10px;color:var(--t2)">'
            "本机日志已连接</span>") if any(s.verified for s in statuses) else ""
    table = (
        "<table><thead><tr><th>平台</th><th>默认路径</th><th>文件</th><th>状态</th>"
        "<th>说明</th></tr></thead><tbody>"
        + ("".join(rows) or '<tr><td colspan="5">未指定数据源</td></tr>')
        + "</tbody></table>"
    )
    return f'<div style="position:absolute;right:22px;top:16px">{live}</div>' + table


def _workspace_card(records: Iterable[UsageRecord], summary: Summary) -> str:
    """工作空间活跃分布：工具栏 + 行（Token / 占比·会话 / 近 7 日分布 sparkbar）。"""
    if not summary.by_workspace:
        return '<div class="cap">暂无数据</div>'
    ws_daily: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for rec in records:
        day = datetime.fromtimestamp(rec.ts).strftime("%Y-%m-%d")
        ws_daily[rec.workspace][day] += rec.total_tokens
    recent_days = sorted({d for w in ws_daily for d in ws_daily[w]})[-7:]
    total = summary.total_tokens or 1
    ranked = sorted(summary.by_workspace, key=lambda w: -summary.by_workspace[w]["tokens"])[:7]
    head = ('<div class="wshead"><span>工作空间</span><span>Token</span><span>占比 / 会话</span>'
            "<span>分布（近 7 个有数据日）</span><span></span></div>")
    rows = []
    for w in ranked:
        info = summary.by_workspace[w]
        sessions = len(summary.ws_sessions.get(w, ()))
        weekly = [ws_daily.get(w, {}).get(d, 0) for d in recent_days]
        week_sum = sum(weekly) or 1
        segs = "".join(
            f'<i class="{"alt" if idx % 2 else ""}" style="width:{v / week_sum * 100:.1f}%"></i>'
            for idx, v in enumerate(weekly) if v
        )
        fallback = "<i style='width:2%'></i>"
        spark = f'<span class="spark">{segs or fallback}</span>'
        name = e(w)
        rows.append(
            f'<div class="wsrow" data-tokens="{info["tokens"]}" data-sessions="{sessions}" '
            f'data-name="{name.lower()}">'
            f'<span class="nm" title="{name}">{name}</span>'
            f'<span class="tk">{fmt(info["tokens"])}</span>'
            f'<span class="sh">{info["tokens"] / total * 100:.1f}%<small>· {sessions} 会话</small></span>'
            f'{spark}<span></span></div>'
        )
    toolbar = (
        '<div class="toolbar">'
        '<span class="mini">按会话</span>'
        '<span class="mini on">按工作空间</span>'
        '<input class="wssearch" id="wsSearch" type="search" placeholder="搜索..." '
        'aria-label="搜索工作空间">'
        '<span class="spacer"></span>'
        '<button class="mini on" id="wsSortTok" type="button">按 Token</button>'
        '<button class="mini" id="wsSortSes" type="button">按会话数</button>'
        '<span class="mini">3X ⌄</span></div>'
    )
    return toolbar + head + f'<div id="wsRows">{"".join(rows)}</div>'


def _model_totals_card(summary: Summary, palette: dict[str, str]) -> str:
    """单模型总量统计：按 Token / 按金额 双口径（CSS 切换），周期跟随全局时间窗口。"""
    if not summary.models:
        return '<div class="cap">暂无数据</div>'
    total_cost = summary.cost_cny or 1.0
    rows = []
    for m in summary.models[:8]:
        info = summary.by_model[m]
        tok_share = info["tokens"] / summary.total_tokens * 100 if summary.total_tokens else 0
        cost_share = info["cost"] / total_cost * 100 if summary.cost_cny else 0
        rows.append(
            f'<tr><td style="color:var(--t1);font-weight:600"><i class="dot" '
            f'style="background:{e(palette[m])}"></i> {e(m)}</td>'
            f'<td class="num"><span class="v-token">{fmt(info["tokens"])}</span>'
            f'<span class="v-cost">¥{info["cost"]:.2f}</span></td>'
            f'<td class="mono">{info["requests"]:,}</td>'
            f'<td class="num" style="color:var(--brandb)">'
            f'<span class="v-token">{tok_share:.1f}%</span>'
            f'<span class="v-cost">{cost_share:.1f}%</span></td></tr>'
        )
    rows.append(
        '<tr class="total"><td>合计</td>'
        f'<td class="num"><span class="v-token">{fmt(summary.total_tokens)}</span>'
        f'<span class="v-cost">¥{summary.cost_cny:.2f}</span></td>'
        f'<td class="mono">{summary.records:,}</td>'
        '<td class="num"><span class="v-token">100%</span><span class="v-cost">100%</span></td></tr>'
    )
    table = (
        '<table><thead><tr><th>模型</th>'
        '<th><span class="v-token">Token 总量</span><span class="v-cost">预估金额（元）</span></th>'
        "<th>请求次数</th>"
        '<th><span class="v-token">Token 占比</span><span class="v-cost">金额占比</span></th>'
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    caption = ("「按 Token / 按金额」可切换显示口径 · 金额按牌价与摊算规则估算 · "
               "缓存写入按 1.25× 输入价 · 单价与汇率详见口径页")
    return (
        '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">'
        "<h3>单模型总量统计</h3>"
        '<div class="seg" id="metricSeg" role="group" aria-label="显示口径切换">'
        '<button type="button" class="on" data-metric-opt="token">按 Token</button>'
        '<button type="button" data-metric-opt="cost">按金额</button></div>'
        '<span class="hdnote" style="margin-left:auto">周期跟随全局时间窗口</span></div>'
        f'<div class="cap">{e(caption)}</div>' + table
    )


def _hourly_card(summary: Summary, palette: dict[str, str]) -> str:
    """0—24 时分布 · 按模型：TOP2 平滑面积曲线。"""
    top = summary.models[:2]
    if not top or not any(summary.hourly):
        return '<div class="cap">暂无数据</div>'
    width, base = 1240, 150
    peak = _nice_max(max(max(summary.hourly_by_model.get(m, [0] * 24)) for m in top))
    step = width / 24.0

    def curve(model: str) -> tuple[str, str]:
        series = summary.hourly_by_model.get(model, [0] * 24)
        pts = [(h * step, base - v / peak * (base - 12)) for h, v in enumerate(series)]
        line = _smooth_path(pts)
        area = f"{line} L{width},{base} L0,{base} Z"
        return line, area

    parts = [f'<svg viewBox="0 0 {width} {base + 34}" role="img" aria-label="0—24 时按模型分布">']
    for frac in (0.2, 0.55):
        y = base - frac * (base - 12)
        parts.append(f'<line x1="0" y1="{y:.1f}" x2="{width}" y2="{y:.1f}" '
                     'stroke="var(--bd)" stroke-width="1"/>')
        parts.append(f'<text x="2" y="{y - 5:.1f}" fill="var(--t3)" font-size="10">{fmt(peak * frac)}</text>')
    parts.append(f'<line x1="0" y1="{base}" x2="{width}" y2="{base}" '
                 'stroke="var(--bds)" stroke-width="1"/>')
    for i, m in enumerate(top):
        line, area = curve(m)
        color = palette[m]
        opacity = 0.16 if i == 0 else 0.12
        parts.append(f'<path d="{area}" fill="{e(color)}" fill-opacity="{opacity}" stroke="none"/>')
        parts.append(f'<path d="{line}" fill="none" stroke="{e(color)}" stroke-width="2"/>')
    for hour in range(0, 24, 2):
        parts.append(f'<text x="{hour * step + 6:.1f}" y="{base + 22}" fill="var(--t3)" '
                     f'font-size="10">{hour}时</text>')
    parts.append("</svg>")
    legend = "".join(
        f'<span><i style="background:{e(palette[m])}"></i>{e(m)} · {e(vendor_of(m))}</span>'
        for m in top
    )
    return f'<div class="legend" style="justify-content:flex-end">{legend}</div>' + "".join(parts)


def _curve_y(hist: Sequence[float], value: float, hi: float) -> float:
    """取分位线落点处的直方图高度（线性插值），让灰点贴在曲线上。"""
    if hi <= 0 or not hist:
        return 0.0
    pos = min(len(hist) - 1.0, max(0.0, value / hi * len(hist)))
    low = int(pos)
    high = min(len(hist) - 1, low + 1)
    frac = pos - low
    return hist[low] * (1 - frac) + hist[high] * frac


def _request_size_card(summary: Summary, palette: dict[str, str]) -> str:
    """单次请求大小分布：左表（次数/50%/90% + 共享刻度对比条）+ 右归一分布曲线。"""
    dist = summary.distribution(top=2)
    models = [d for d in dist["models"] if d["count"]]
    if not models:
        return '<div class="cap">暂无数据</div>'
    cap = max(d["p90"] for d in models) or 1

    head = ('<div class="dhead drow" style="border-bottom:1px solid var(--bd)">'
            "<span>模型</span><span>次数</span><span>50%</span><span>90%</span></div>")
    rows = []
    for d in models:
        color = palette.get(d["name"], "#5FC2A0")
        cells = f'<span class="nm">{e(d["name"])}</span><span class="val">{d["count"]}</span>'
        for key, label_, shade in (("p50", "50%", 0.0), ("p90", "90%", 0.45)):
            value = d[key]
            bar_color = _blend(color, "#FFFFFF", shade)
            cells += (
                f'<span class="val">{fmt(value)}<small>{label_}'
                f'<i style="width:{value / cap * 100:.1f}%;background:{e(bar_color)}"></i>'
                "</small></span>"
            )
        rows.append(f'<div class="drow">{cells}</div>')
    left = head + "".join(rows)

    # 每模型直方图（各自归一），Catmull-Rom 平滑
    width, base = 860, 150
    hi = _nice_max(max(d["p90"] for d in models) * 1.35)
    bins = 28
    hists: dict[str, list[float]] = {}
    for d in models:
        sizes = summary.model_sizes.get(d["name"], [])
        hist = [0] * bins
        for v in sizes:
            idx = min(bins - 1, int(v / hi * bins))
            hist[idx] += 1
        peak = max(hist) or 1
        hists[d["name"]] = [h / peak for h in hist]
    step = width / bins
    parts = [f'<svg viewBox="0 0 {width} {base + 26}" role="img" aria-label="单次请求大小分布">']
    parts.append(f'<line x1="0" y1="{base}" x2="{width}" y2="{base}" '
                 'stroke="var(--bds)" stroke-width="1"/>')
    for d in models:
        color = palette.get(d["name"], "#5FC2A0")
        pts = [(i * step + step / 2, base - v * (base - 16))
               for i, v in enumerate(hists[d["name"]])]
        line = _smooth_path(pts)
        parts.append(f'<path d="{line} L{width},{base} L0,{base} Z" '
                     f'fill="{e(color)}" fill-opacity="0.14"/>')
        parts.append(f'<path d="{line}" fill="none" stroke="{e(color)}" stroke-width="2"/>')
        x50 = d["p50"] / hi * width
        parts.append(f'<line x1="{x50:.1f}" y1="26" x2="{x50:.1f}" y2="{base}" '
                     f'stroke="{e(color)}" stroke-width="1.5" stroke-opacity=".8"/>')
        y90 = base - _curve_y(hists[d["name"]], d["p90"], hi) * (base - 16)
        parts.append(f'<circle cx="{d["p90"] / hi * width:.1f}" cy="{y90:.1f}" r="3.5" fill="#8A9A90"/>')
    gx = dist["global_p50"] / hi * width
    parts.append(f'<line x1="{gx:.1f}" y1="14" x2="{gx:.1f}" y2="{base}" '
                 'stroke="var(--t3)" stroke-width="1" stroke-dasharray="4 4"/>')
    parts.append(f'<text x="{min(width - 4, gx + 6):.1f}" y="24" fill="var(--t3)" font-size="10">'
                 f'全局 50% {fmt(dist["global_p50"])}</text>')
    for frac in (0, 1 / 3, 2 / 3, 1):
        anchor = ' text-anchor="end"' if frac == 1 else ""
        label_ = "0" if frac == 0 else fmt(hi * frac)
        parts.append(f'<text x="{width * frac:.1f}" y="{base + 20}" fill="var(--t3)" '
                     f'font-size="10"{anchor}>{label_}</text>')
    parts.append("</svg>")
    caption = ("每模型一条分布形状（各自归一）· 实线=该模型 50% · 灰点=90% · 虚线=全局 50% · "
               "数值下条形=两列共享刻度的大小对比（深=50% 浅=90%）")
    return (
        f'<div class="distwrap"><div>{left}</div><div>{"".join(parts)}'
        f'<div class="cap" style="margin-top:8px">{e(caption)}</div></div></div>'
    )


def _dayhour_card(summary: Summary) -> str:
    """日活分布：四时段占比卡 + 最近 3 个有数据日 × 24 小时热力图。"""
    if not summary.hour_matrix:
        return '<div class="cap">暂无数据</div>'
    band_total = sum(summary.bands) or 1
    band_names = ("凌晨 0—6", "上午 6—12", "下午 12—18", "晚间 18—24")
    chips = "".join(
        f'<div class="chip2"><span>{e(n)}</span><b>{v / band_total * 100:.1f}%</b></div>'
        for n, v in zip(band_names, summary.bands)
    )
    days = sorted(summary.hour_matrix)[-3:][::-1]
    peak = max((v for d in days for v in summary.hour_matrix[d]), default=0) or 1
    cell, gap = 40, 6
    width = 24 * (cell + gap)
    row_h, row_gap = 16, 8
    height = len(days) * (row_h + row_gap)
    parts = [f'<svg viewBox="0 0 {width} {height + 24}" role="img" aria-label="日 × 小时热力图">']
    for hour in range(24):
        parts.append(f'<text x="{hour * (cell + gap) + 12}" y="12" fill="var(--t3)" '
                     f'font-size="9" text-anchor="middle">{hour}</text>')
    for r, day in enumerate(days):
        y = 22 + r * (row_h + row_gap)
        for hour in range(24):
            v = summary.hour_matrix[day][hour]
            level = 0 if v <= 0 else min(6, 1 + int(v / peak * 5.999))
            parts.append(
                f'<rect x="{hour * (cell + gap)}" y="{y}" width="{cell}" height="{row_h}" rx="3" '
                f'fill="var(--h{level})"><title>{e(day)} {hour}:00 · {fmt(v)}</title></rect>'
            )
    parts.append("</svg>")
    row_labels = "".join(
        f'<div style="height:{row_h + row_gap}px;display:flex;align-items:center;'
        f'font-family:var(--mono);font-size:10px;color:var(--t2)">'
        f'{e(day[5:7])}—{e(day[8:10])}</div>'
        for day in days
    )
    swatches = "".join(f'<i style="background:var(--h{i})"></i>' for i in range(7))
    legend = f'<div class="hmlegend">低 {swatches} 高</div>'
    body = ('<div style="display:grid;grid-template-columns:76px 1fr;gap:10px;align-items:start">'
            f'<div style="padding-top:22px">{row_labels}</div><div>{"".join(parts)}</div></div>')
    return f'<div class="chips">{chips}</div>{legend}{body}'


# ------------------------------------------------------------------ 入口

def render_html(
    summary: Summary,
    records: Sequence[UsageRecord],
    statuses: Sequence[SourceStatus] = (),
    *,
    theme_name: str = "light",
    title: str = "TokenBoard · 消耗洞察",
    generated: str | None = None,
    window_note: str = "",
    window_label: str = "近 30 天",
) -> str:
    """渲染完整的单文件 HTML；不访问网络、不写文件。"""
    generated = generated or datetime.now().strftime("%Y-%m-%d %H:%M")
    kpi = summary.kpi()
    palette = palette_for(summary.models)

    hero = _hero(summary, window_note)
    kpis = _kpi_cards([
        ("合计 Token", fmt(summary.total_tokens), "", True),
        ("请求轮次", f'{kpi["requests"]:,}', "", False),
        ("缓存命中率", f'{kpi["cache_hit_rate"]:.1f}', "%", False),
        ("预估金额（元）", f'¥{kpi["estimated_cost_cny"]:.2f}', "", False),
    ])
    kpi2 = _kpi_cards([
        ("日均（有数据天）", fmt(summary.daily_average), "", False),
        ("会话", f'{kpi["sessions"]:,}', "", False),
        ("输入 / 输出比", f'{kpi["input_output_ratio"]:.1f} : 1', "", False),
    ])
    s1_note = f"{e(window_label)}&ensp;·&ensp;{kpi['active_days']} 个有数据日"

    periods = []
    for lbl in ("1 天", "3 天", "近 7 天", "近 30 天"):
        on = ' class="on"' if lbl == window_label else ""
        periods.append(f"<span{on}>{e(lbl)}</span>")
    if window_label not in ("1 天", "3 天", "近 7 天", "近 30 天"):
        periods.append(f'<span class="on">{e(window_label)}</span>')
    period_pills = "".join(periods)

    distribution_section = (
        '<div class="card"><h3>工作空间活跃分布</h3>'
        + _workspace_card(records, summary) + "</div>"
        + '<div class="card">' + _model_totals_card(summary, palette) + "</div>"
        + '<div class="card"><h3>0—24 时分布 · 按模型</h3>' + _hourly_card(summary, palette) + "</div>"
        + '<div class="card"><h3>单次请求大小分布&ensp;<span class="hdnote">'
        f'TOP {min(2, len(summary.models))} 模型 · 共 {summary.records:,} 次</span></h3>'
        + _request_size_card(summary, palette) + "</div>"
        + '<div class="card"><h3>日活分布&ensp;<span class="hdnote">色深代表当日该小时的消耗强度</span></h3>'
        + _dayhour_card(summary) + "</div>"
    )

    footer = (
        f"生成时间 {e(generated)} · 数据来自本机会话日志，不外发、无外部依赖<br>"
        "口径：请求级真实 usage；金额按牌价估算，缓存读命中走缓存价、缓存写入按输入价 ×1.25、"
        "其余输入走输入价，输出走输出价。不同套餐单价请用 --prices 覆盖；"
        "统计周期跟随全局时间窗口，空窗日不参与日均计算。<br>"
        "绿色系用于 UI 框架，厂商品牌色仅用于数据系列且始终附文字标签（WCAG 1.4.1）。"
        "未验证平台只表示「本机没有真实日志可供核对」，不代表功能已支持。"
    )
    subtitle = f"请求级真实 usage · 多平台统一口径 · 数据截至 {e(generated)}"

    css = (
        _CSS.replace("__SANS__", _SANS)
        .replace("__MONO__", _MONO)
        .replace("__LIGHT__", _vars(GREEN_LIGHT))
        .replace("__DARK__", _vars(GREEN_DARK))
        .replace("__HEAT_L__", _heat_vars("light"))
        .replace("__HEAT_D__", _heat_vars("dark"))
    )
    replacements = {
        "__TITLE__": e(title),
        "__SUBTITLE__": subtitle,
        "__THEME__": "light" if theme_name == "light" else "dark",
        "__GENERATED__": e(generated),
        "__CSS__": css,
        "__PERIODS__": period_pills,
        "__HERO__": hero,
        "__KPIS__": kpis,
        "__S1NOTE__": s1_note,
        "__KPI2__": kpi2,
        "__MODELCAP__": (
            "同厂商模型用明度阶梯区分，色相保持品牌体系 · "
            f"全局 50% 单次请求 {fmt(summary.global_p50)}"
        ),
        "__MODELS__": _model_card(summary, palette),
        "__DAILY__": _daily_card(records, summary, palette),
        "__SOURCES__": _sources_card(statuses),
        "__DISTRIBUTION__": distribution_section,
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

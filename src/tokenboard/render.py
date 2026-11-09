# -*- coding: utf-8 -*-
"""单文件离线 HTML 渲染（v0.3：静态首屏 + 页内交互引擎）。

设计约束（与 docs/DESIGN_TOKENS.md、Ardot 定稿设计稿三方一致）：
  * UI 框架只用 :mod:`tokenboard.brands` 的绿色系令牌；
  * 品牌色只出现在数据系列，并且永远配文字标签；
  * 零外部请求、零第三方库，生成的 HTML 断网也能看；
  * 浅色为默认主题（白底荧光绿），深色为「暗夜玻璃」变体，运行时切换。

交互：
  * 周期胶囊 / 自定义日期范围 **真切换**：请求级明细以分钟粒度嵌入页面，
    JS 端按同一口径重新聚合，重绘全部指标与图表；
  * 工作空间 → 会话 → 请求 三级下钻（散点 / 明细表）+ 面包屑返回；
  * 模型点选聚焦（其余模型在图表中变暗）、跟随式 tooltip、3X 切片。

模板用 ``str.replace`` 注入而不是 f-string，避免 CSS/JS 里大量花括号被误解释。
"""
from __future__ import annotations

import html
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

from .aggregate import (
    DEFAULT_DIST_TOP,
    DEFAULT_HOUR_TOP,
    DEFAULT_WS_TOP,
    Summary,
)
from .brands import GREEN_DARK, GREEN_LIGHT, HEATMAPS, palette_for, vendor_of
from .models import SourceStatus, UsageRecord
from .pricing import price_of

_SANS = '-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif'
_MONO = 'ui-monospace,"JetBrains Mono",SFMono-Regular,Menlo,Consolas,monospace'

# 看板页面默认聚焦的展示窗口。只影响「周期胶囊初始高亮 + JS 聚合窗口」，
# 不改变扫描口径：无 --since 时仍扫描全部历史并把请求级明细全量嵌入 HTML，
# 因此用户随时可切到近 30 天 / 总量。CLI 与 serve 共用这两个常量，避免首屏不一致。
DEFAULT_VIEW_DAYS = 1
DEFAULT_VIEW_LABEL = "1 天"

_CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
:root{--sans:__SANS__;--mono:__MONO__}
body{font-family:var(--sans);background:var(--bg);color:var(--t1);padding:24px 26px 56px;
max-width:1560px;margin:0 auto;-webkit-font-smoothing:antialiased}
body[data-theme=light]{__LIGHT_CSS__ __HEAT_L_CSS__}
body[data-theme=dark]{__DARK_CSS__ __HEAT_D_CSS__;
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
.twin button{border:none;background:transparent;color:var(--t2);font-size:11px;padding:5px 13px;
border-radius:7px;white-space:nowrap;cursor:pointer;font-family:var(--sans)}
.twin button.on{background:var(--brandsoft);color:var(--brandb);font-weight:600;
box-shadow:inset 0 0 0 1px var(--brand)}
.drange{display:flex;align-items:center;gap:6px;font-size:10.5px;color:var(--t2)}
.drange input{border:1px solid var(--bd);background:var(--surface);color:var(--t1);
-webkit-text-fill-color:var(--t1);border-radius:7px;
padding:5px 8px;font-size:10.5px;font-family:var(--mono)}
/* 日期输入内部文字必须走 text_1 主文字（配色规范 §6），
   不再把 color-scheme 交给系统偏好决定，避免浅色主题下日期文字被 UA 画成浅色 */
body[data-theme=light] .drange input{color-scheme:light}
body[data-theme=dark] .drange input{color-scheme:dark}
/* 「指定日」融合日期选择：整颗 pill 即触发原生日历，选定后显示该日期并高亮。
   宽度只比最宽的周期按钮略大，刚好完整容纳 YYYY-MM-DD（等宽字体），不留大片空白。 */
.dpill{position:relative;display:inline-flex;align-items:center;justify-content:center;
height:30px;min-width:108px;padding:0 8px;border:1px solid var(--bd);border-radius:9px;
background:var(--surface);color:var(--t1);font-size:11px;font-family:var(--mono);
cursor:pointer;opacity:.72;white-space:nowrap;-webkit-user-select:none;user-select:none;
transition:opacity .15s,border-color .15s,color .15s}
.dpill.on{opacity:1;border-color:var(--brand);box-shadow:inset 0 0 0 1px var(--brand);color:var(--brandb)}
.dpill #dayPickTxt{position:relative;z-index:2;pointer-events:none}
.dpill input{position:absolute;inset:0;z-index:1;width:100%;height:100%;border:none;
background:transparent;opacity:0;cursor:pointer;font-family:var(--mono)}
body[data-theme=light] .dpill input{color-scheme:light}
body[data-theme=dark] .dpill input{color-scheme:dark}
/* ---- 结论条 ---- */
.hero{position:relative;background:var(--surface);border:1px solid var(--bds);border-radius:20px;
padding:20px 26px 18px;margin-bottom:16px;overflow:hidden}
.hero:before{content:"";position:absolute;left:0;top:20px;bottom:20px;width:3px;
border-radius:2px;background:var(--brand)}
.hero .lab{font-size:10px;letter-spacing:.18em;color:var(--t2)}
.hero .main{font-size:28px;font-weight:700;margin-top:8px;line-height:1.35;font-variant-numeric:tabular-nums}
.hero .sub2{font-size:11.5px;color:var(--t2);margin-top:8px}
.hero .warn{font-size:10.5px;color:var(--warn);margin-top:12px;min-height:0}
.hero .side{position:absolute;right:26px;top:30px;text-align:right}
.hero .side .k{font-size:10px;color:var(--t2)}
.hero .side .v{font-family:var(--mono);font-size:18px;font-weight:700;margin-top:5px}
/* ---- KPI ---- */
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:8px}
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
.kpis{grid-template-columns:repeat(2,1fr)}.chips{grid-template-columns:repeat(2,1fr)}}
/* ---- 模型条 ---- */
/* 名字列宽度由 JS 测量所有模型名（含厂商 chip）后写入 --nmw，保证完整显示；
   上限 cap 在 max(200px, 42vw)，极长名超出上限仍走省略号，条形列永远保底可见 */
.mrow{display:grid;grid-template-columns:var(--nmw,200px) minmax(160px,2fr) minmax(190px,300px) minmax(110px,170px);
gap:12px;align-items:center;padding:9px 0;font-size:11.5px}
.mrow .nm{font-family:var(--mono);font-weight:600;color:var(--t1);overflow:hidden;
text-overflow:ellipsis;white-space:nowrap;cursor:pointer}
.mrow .nm.sans{font-family:var(--sans);font-weight:500;cursor:default}
.mrow .nm .dot{margin-right:6px}
.mrow.dim .track i{opacity:.28}
.mrow.dim .nm,.mrow.dim .num{opacity:.45}
.mrow .track{height:12px;background:var(--surface2);border-radius:8px;overflow:hidden}
.mrow .track i{display:block;height:100%;border-radius:8px;transition:opacity .15s}
/* 输入/输出构成条：两段加起来正好 100%，各自不被 flex 压缩 */
.mrow .num{font-family:var(--mono);font-size:10.5px;color:var(--t2);text-align:right;
font-variant-numeric:tabular-nums;white-space:nowrap}
.dot{width:9px;height:9px;border-radius:3px;flex:none;display:inline-block;vertical-align:-1px}
.vendor{font-size:9px;color:var(--t3);border:1px solid var(--bd);border-radius:4px;
padding:1px 5px;margin-left:6px}
/* 按模型消耗行末的「平台」列：该模型在哪些平台被使用（窗口口径，与左侧数值一致） */
.mrow .plats{display:flex;flex-wrap:wrap;gap:3px;align-content:center}
.pchip{font-size:8.5px;line-height:1.5;color:var(--t2);background:var(--surface2);
border:1px solid var(--bd);border-radius:4px;padding:1px 5px;white-space:nowrap}
.mrow.dim .plats{opacity:.45}
/* ---- 通用表 ---- */
table{width:100%;border-collapse:collapse;font-size:11.5px}
th{text-align:left;font-weight:500;color:var(--t3);font-size:10px;padding:8px 8px;
border-bottom:1px solid var(--bd)}
td{padding:10px 8px;border-bottom:1px solid var(--bd);color:var(--t2)}
tbody tr:last-child td{border-bottom:none}
td.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
td.num{font-family:var(--mono);color:var(--t1);font-weight:600}
tr.total td{border-top:1px solid var(--bds);border-bottom:none;color:var(--t1);font-weight:600}
/* 状态徽章禁止折行：中文列太窄时会被拆成两行（已验/证），加 nowrap 保持单行 */
.pill{font-size:9.5px;padding:2px 8px;border-radius:999px;border:1px solid var(--bd);
white-space:nowrap;word-break:keep-all;display:inline-block}
.pill.ok{color:var(--ok);border-color:var(--ok)}
.pill.no{color:var(--warn);border-color:var(--warn)}
.livedot{width:8px;height:8px;border-radius:50%;background:var(--brand);display:inline-block;margin-right:6px}
/* 数据源表「导入状态」列：按钮 + 状态徽章同一行，窄屏也不折行 */
.impcell{white-space:nowrap}
.impbtn{border:1px solid var(--brand);background:var(--brandsoft);color:var(--brandb);
font-size:10px;padding:4px 10px;border-radius:7px;cursor:pointer;font-family:var(--sans);font-weight:600}
.impbtn:hover{filter:brightness(.96)}
.impbtn.ghost{border-color:var(--bd);background:var(--surface);color:var(--t2);font-weight:400}
.impbtn[disabled]{opacity:.55;cursor:wait}
.impst{font-size:9.5px;margin-left:8px;white-space:nowrap}
.impst.yet{color:var(--t3)}
.impst.ok{color:var(--ok);font-weight:600}
.impst.warn{color:var(--warn)}
/* ---- 工作空间卡 ---- */
.crumb{display:none;align-items:center;gap:8px;margin:2px 0 10px;font-size:11px;color:var(--t2)}
.crumb .path .sep{margin:0 7px;color:var(--t3)}
.crumb .cur{color:var(--t1);font-weight:600}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0 4px}
.toolbar .spacer{flex:1}
.mini{border:1px solid var(--bd);background:var(--surface);color:var(--t2);font-size:10px;
padding:5px 11px;border-radius:7px;cursor:pointer;font-family:var(--sans)}
.mini.on{background:var(--brandsoft);border-color:var(--brand);color:var(--brandb);font-weight:600}
.mini:hover{border-color:var(--bds)}
/* 卡片头：标题 + 说明 + 右侧下拉。说明必须 min-width:0 可收缩，否则长文案会把
   select 挤出卡片右边界造成控件被裁；下拉 flex:none，并留足原生箭头空间与最小宽度 */
.cardhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.cardhead>h3{flex:0 0 auto}
.cardhead>.hdnote{flex:1 1 180px;min-width:0}
select.mini{padding:5px 20px 5px 9px;color-scheme:light dark;white-space:nowrap}
.cardhead>select.mini{flex:0 0 auto;min-width:100px;margin-left:auto}
.cardhead>select.mini.wide{min-width:132px}
/* 工作空间 & 会话消耗活跃分布卡：平台链（列出涉及的全部平台，随全局平台筛选联动） */
.pchip{font-size:10px;line-height:1.5;padding:1px 7px;border:1px solid var(--bd);
  border-radius:999px;background:var(--surface);color:var(--t2);white-space:nowrap}
.pchip:hover{border-color:var(--bds)}
/* 0—24 时分布卡有两个下拉（模型数量 + 时间口径）：用不可收缩容器一起靠右，
   避免两个 margin-left:auto 互相抢空间、把说明挤没或裁掉第二个控件 */
.hdtools{display:flex;align-items:center;gap:8px;flex:0 0 auto;margin-left:auto}
.hdtools>select.mini{flex:0 0 auto;min-width:100px}
.wssearch{border:1px solid var(--bd);background:var(--surface);color:var(--t1);font-size:10.5px;
padding:5px 10px;border-radius:7px;width:130px;outline:none;font-family:var(--sans)}
.wssearch:focus{border-color:var(--bds)}
.wshead{display:grid;grid-template-columns:minmax(140px,1.2fr) 96px 110px 140px 1fr 18px;gap:12px;
font-size:10px;color:var(--t3);padding:8px 0;border-bottom:1px solid var(--bd)}
.wsrow{display:grid;grid-template-columns:minmax(140px,1.2fr) 96px 110px 140px 1fr 18px;gap:12px;
align-items:center;padding:9px 0;border-bottom:1px solid var(--bd);font-size:10.5px}
.wsrow:last-child{border-bottom:none}
.wsrow.click{cursor:pointer}
.wsrow.click:hover{background:var(--surface2)}
.wsrow .nm{font-family:var(--mono);color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wsrow .wplat{display:flex;flex-wrap:wrap;gap:3px;align-items:center;overflow:hidden}
.wsrow .tk{font-family:var(--mono);color:var(--t1);font-variant-numeric:tabular-nums}
.wsrow .sh{color:var(--brandb);font-family:var(--mono)}
.wsrow .sh small{color:var(--t3);margin-left:4px}
.wsrow .chev{color:var(--t3);text-align:center}
.strow{display:grid;grid-template-columns:minmax(180px,1.8fr) 86px minmax(130px,1fr) 110px 128px;
gap:12px;align-items:center;padding:9px 0;border-bottom:1px solid var(--bd);font-size:10.5px}
.strow:last-child{border-bottom:none}
.strow.click{cursor:pointer}
.strow.click:hover{background:var(--surface2)}
.strow .nm{color:var(--t1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.strow .tk{font-family:var(--mono);color:var(--t1);font-variant-numeric:tabular-nums}
.strow .sh{color:var(--brandb);font-family:var(--mono)}
.strow .sh small{color:var(--t3);margin-left:4px}
.strow .wsn{color:var(--t3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.strow .plat{font-family:var(--mono);font-size:9.5px;color:var(--brandb)}
.ptag{display:inline-block;font-size:9px;color:var(--brandb);border:1px solid var(--bds);
border-radius:5px;padding:1px 5px;margin-left:6px;vertical-align:middle;font-family:var(--mono)}
.wviz{display:flex;gap:2px;height:9px;align-items:stretch}
.wviz i{flex:1;border-radius:2px}
/* ---- 长列表滚动：表头吸顶，内容不足时自动不出现滚动条 ---- */
.scrollbox{max-height:380px;overflow-y:auto;overscroll-behavior:contain;padding-right:4px;
scrollbar-width:thin;scrollbar-color:var(--bds) transparent}
.scrollbox::-webkit-scrollbar{width:9px}
.scrollbox::-webkit-scrollbar-track{background:transparent}
.scrollbox::-webkit-scrollbar-thumb{background:var(--bds);border-radius:9px;
border:2px solid var(--surface)}
.scrollbox::-webkit-scrollbar-thumb:hover{background:var(--brand)}
.scrollbox .wshead,.scrollbox .sthead{position:sticky;top:0;z-index:2;
background:var(--surface);box-shadow:0 1px 0 var(--bd)}
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
.legend span{font-size:10.5px;color:var(--t2);display:flex;align-items:center;gap:6px;cursor:pointer}
.legend span.pinned{cursor:default}
.legend i{width:10px;height:10px;border-radius:3px;display:inline-block}
.distwrap{display:grid;grid-template-columns:340px 1fr;gap:22px;align-items:start}
@media(max-width:980px){.distwrap{grid-template-columns:1fr}}
.drow{display:grid;grid-template-columns:76px 48px 1fr 1fr;gap:10px;align-items:center;
padding:10px 0;border-bottom:1px solid var(--bd);font-size:11px}
.drow:last-child{border-bottom:none}
.dhead{font-size:10px;color:var(--t3)}
.dhead.drow{padding:0 0 2px}
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
/* ---- 会话详情 / 请求明细 ---- */
.view-h{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;
margin:4px 0 12px}
.view-t{font-size:13px;font-weight:650;color:var(--t1);font-family:var(--mono)}
.view-m{font-size:10.5px;color:var(--t3);margin-top:4px;font-family:var(--mono)}
.rt-wrap{max-height:360px;overflow:auto;border:1px solid var(--bd);border-radius:10px}
/* ---- tooltip ---- */
#tip{position:fixed;z-index:99;background:var(--t1);color:var(--bg);font-size:10.5px;line-height:1.55;
padding:7px 10px;border-radius:8px;pointer-events:none;opacity:0;transition:opacity .08s;
max-width:280px;white-space:pre-line;font-family:var(--mono)}
/* 0—24 时分布的悬停竖线：底部留 34/184（基线以下坐标区）不遮挡时刻标签 */
#hourChart .hchart{position:relative}
#hourChart .hxline{position:absolute;top:0;bottom:18.5%;width:1px;display:block;
background:var(--t2);opacity:0;pointer-events:none;transition:opacity .08s}
.foot{margin-top:28px;padding-top:14px;border-top:1px solid var(--bd);font-size:10.5px;
color:var(--t3);line-height:1.9}
"""

_TEMPLATE = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>__CSS__</style></head>
<body data-theme="__THEME__" data-metric="token">
<div class="crumbrow"><span>总览&ensp;/&ensp;消耗洞察</span>
<span>数据截至 __GENERATED__ · 离线可用 · 周期 / 图例 / 工作空间均可点击</span></div>
<div class="titlerow"><div><h1>__TITLE__</h1><div class="sub">__SUBTITLE__</div></div>
<div class="controls">
<div class="twin" id="periodPills">__PERIODS__</div>
<label class="dpill" id="dayPick" title="点击选择具体某一天；选定后整颗 pill 即显示该日期">
<span id="dayPickTxt">指定日</span>
<input type="date" id="daySel" aria-label="选择具体日期" value="__DAYVAL__" min="__DAYMIN__" max="__DAYMAX__"></label>
<div class="drange"><input type="date" id="dStart" aria-label="起始日期">至
<input type="date" id="dEnd" aria-label="结束日期"></div>
<select class="mini" id="platSel" aria-label="平台筛选">__PLATOPTS__</select>
<button class="chip" id="themeBtn">深色</button>
<button class="chip" id="refreshBtn" title="重新扫描本机日志并刷新数据（需通过 tokenboard serve 打开；双击文件时仅重载当前快照）">刷新</button>
<button class="chip" onclick="window.print()">导出 PDF</button></div></div>
__HERO__
<div class="kpis" id="kpis">__KPIS__</div>
<div class="sec"><b>01</b><h2>模型与品牌色</h2><span>点击模型名或图例可聚焦单个模型</span></div>
<div class="duo">
<div class="card"><h3>按模型消耗</h3><div class="cap" id="modelCap">__MODELCAP__</div>
<div id="modelRows">__MODELS__</div></div>
<div class="card"><div class="cardhead">
<h3>每日用量趋势</h3><span class="hdnote" id="dailyNote">按模型堆叠 · 点击图例聚焦 · 单位 Token · 总量口径</span>
<div class="hdtools" id="dailySpan">
<button type="button" class="mini" data-span="1">1日</button>
<button type="button" class="mini" data-span="3">3日</button>
<button type="button" class="mini on" data-span="7">7日</button>
<button type="button" class="mini" data-span="month">本月</button>
</div></div>
<div id="dailyChart">__DAILY__</div></div>
</div>
<div class="sec"><b>02</b><h2>数据源状态与口径</h2><span>下钻顺序：平台 → 工作空间 → 会话 → 请求</span></div>
<div class="card">__SOURCES__</div>
<div class="sec"><b>03</b><h2>使用分布与时间节律</h2><span>工作空间 / 请求规模 / 日活 / 时段 / 模型构成</span></div>
<div class="card"><div id="wsCrumb" class="crumb"></div>
<div class="cardhead"><h3 id="wsTitle">工作空间 &amp; 会话消耗活跃分布</h3>
<span class="hdnote" id="wsNote">__WSNOTE__</span>
<select class="mini wide" id="wsTop" aria-label="显示工作空间数量">__WSOPTS__</select></div>
<div id="wsTools">
<div class="toolbar">
<span class="mini" data-m="ses">按会话</span>
<span class="mini on" data-m="ws">按工作空间</span>
<input class="wssearch" id="wsSearch" type="search" placeholder="搜索..." aria-label="搜索">
<span class="spacer"></span>
<button class="mini on" data-s="tokens" type="button">按 Token</button>
<button class="mini" data-s="sessions" type="button">按会话数</button>
<select class="mini" id="wsGran" aria-label="分布粒度">
<option value="day" selected>日 · 当日 24 时</option><option value="week">周 · 当周 7 天</option>
<option value="month">月 · 当月</option></select></div></div>
<div id="wsPanel" class="scrollbox">__WORKSPACES__</div></div>
<div class="card" id="mtCard">__MODEL_TOTALS__</div>
<div class="card"><div class="cardhead">
<h3>0—24 时分布 · 按模型</h3><span class="hdnote" id="hourNote">当日看节律 · 累计看总量 · 悬浮看该小时各模型消耗</span>
<div class="hdtools">
<select class="mini" id="hourTop" aria-label="0—24 时分布显示模型数量">__HOUROPTS__</select>
<select class="mini" id="hourMode" aria-label="0—24 时分布口径">
<option value="all" selected>累计</option><option value="today">仅当日</option></select>
</div></div>
<span class="hdnote" id="hourSub">每条曲线 = 全部数据在同一时段的消耗总和（不限时间窗口） · 点击图例聚焦单个模型 · 悬浮看该小时各模型消耗</span><div id="hourChart">__HOURLY__</div></div>
<div class="card"><div class="cardhead">
<h3>单次请求大小分布</h3><span class="hdnote" id="distNote">__DISTNOTE__</span>
<select class="mini" id="distTop" aria-label="显示模型数量">
<option value="2">TOP 2</option><option value="3" selected>TOP 3</option>
<option value="5">TOP 5</option><option value="8">TOP 8</option>
<option value="0">全部模型</option></select></div>
<div id="distBody">__REQDIST__</div></div>
<div class="card"><h3>日活分布&ensp;<span class="hdnote">色深代表当日该小时的消耗强度 · 悬浮看数值</span></h3>
<div id="dayhourCard">__DAYHOUR__</div></div>
<div class="foot">__FOOTER__</div>
<div id="tip"></div>
<script>window.TB_DATA=__DATA__;</script>
<script>window.TB_IMPORTED=__IMPORTED__;</script>
<script>__SCRIPT__</script></body></html>"""

_SCRIPT = r"""
(function(){
"use strict";
var D=window.TB_DATA||{};
var $=function(s){return document.querySelector(s)};
var HEAT_L=__HEAT_L_JS__,HEAT_D=__HEAT_D_JS__;
var DARK=document.body.dataset.theme==='dark',HEAT=DARK?HEAT_D:HEAT_L;
var models=D.models||[],PAL=D.palette||[],VENDOR=D.vendor||[],PRICE=D.prices||[];
var WS=D.workspaces||[],SESS=D.sessions||[],PLAT=D.platforms||[];
var genMin=D.genMin||0;
/* dayAnchor = 生成当日结束（次日 00:00，分钟）。周期窗口与日活热力都以它为锚，
   保证「近 N 天」始终是含当日的 N 个自然日，而不是最后一条日志往前的滚动 168 小时。
   兼容旧页面：没有 dayAnchor 时退回 genMin。 */
var dayAnchor=D.dayAnchor||genMin;
function todayDate(){return new Date((dayAnchor-1440)*60000);} // 当日 00:00
var win=(D.win!=null?D.win:__VIEW_DAYS__),cLo=D.custom?D.custom[0]:0,cHi=D.custom?D.custom[1]:0;
if(D.custom)win=0;
var wsSort='tokens',q='',state={ws:null,ses:null},selModel=null,wsGran='day',wsMode='ws';
var platFilter=-1;
var heatView='day';   // 日活分布视图：day=7天×24小时 / week=近7天每天 / month=近30天每天
var distTop=__DIST_TOP__;  // 单次请求大小分布显示的模型数（0=全部），与 Python 常量同源
var wsTop=__WS_TOP__;      // 工作空间活跃分布显示的条数（0=全部），与 Python 常量同源
var hourTop=__HOUR_TOP__;  // 0—24 时分布显示的曲线数（0=全部），与 Python 常量同源
var hourMode='all';  // 0—24 时分布口径：all=全部数据累计（不限窗口）/ today=仅聚焦日逐时
var dailySpan='7';   // 每日用量趋势可见跨度：1 / 3 / 7 个自然日 或 本月（month），数据按总量口径
/* 指定日模式：选定一个自然日后，所有卡片只聚合这一天。
   与周期胶囊、自定义日期区间互斥；dayKey 形如 'YYYY-MM-DD'。 */
var dayMode=false,dayKey='';
var allMode=false;   // 总量模式：跨全部日期累计，不受近 N 天窗口限制
/* 嵌入数据的最早一条记录时间戳（分钟）；总量模式以它为下界，覆盖全部历史。 */
var dataMinMin=Infinity;
for(var _si=0;_si<SESS.length;_si++){var _rs=SESS[_si].r;if(_rs&&_rs.length)dataMinMin=Math.min(dataMinMin,_rs[0][0]);}
if(!isFinite(dataMinMin))dataMinMin=0;
var LASTA=null;

/* ---------------- 基础工具 ---------------- */
function fmt(n){n=+n||0;if(n>=1e8)return (n/1e8).toFixed(2)+' 亿';
  if(n>=1e4)return (n/1e4).toFixed(1)+' 万';return String(Math.round(n));}
function nf(n){return (+n||0).toLocaleString('en-US');}
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function fm(d){var p=function(v){return (v<10?'0':'')+v};
  return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());}
function fd(d){var p=function(v){return (v<10?'0':'')+v};return (d.getMonth()+1)+'-'+p(d.getDate());}
function ft(d){var p=function(v){return (v<10?'0':'')+v};return p(d.getHours())+':'+p(d.getMinutes());}
function pct(a,b){return b?a/b*100:0;}
function priceOf(mi){return PRICE[mi]||[2,8,0.4];}
function cost(r){var p=priceOf(r[1]),inp=r[3],out=r[4];
  var cr=Math.max(0,Math.min(r[5]||0,inp)),rem=Math.max(0,inp-cr);
  var cw=Math.max(0,Math.min(r[6]||0,rem)),plain=Math.max(0,rem-cw);
  return (cr*p[2]+cw*1.25*p[0]+plain*p[0]+out*p[1])/1e6;}
function pctile(v,q){if(!v||!v.length)return 0;var a=v.slice().sort(function(x,y){return x-y;});
  if(a.length===1)return a[0];var k=(a.length-1)*q/100,lo=Math.floor(k),hi=Math.ceil(k);
  if(lo===hi)return a[lo];return a[lo]+(a[hi]-a[lo])*(k-lo);}
function niceMax(v){if(!(v>0))return 1;var mag=Math.pow(10,Math.floor(Math.log(v)/Math.LN10));
  var f=[1,2,2.5,5,10];for(var i=0;i<f.length;i++){if(v<=f[i]*mag)return f[i]*mag;}return 10*mag;}
function smoothLine(pts){ /* Fritsch-Carlson 单调三次插值，平滑且不过冲 */
  var n=pts.length;if(n<3)return 'M'+pts.map(function(p){return p[0].toFixed(1)+' '+p[1].toFixed(1);}).join(' L');
  var dx=[],m=[],t=new Array(n),i;
  for(i=0;i<n-1;i++)dx.push(pts[i+1][0]-pts[i][0]);
  for(i=0;i<n-1;i++)m.push((pts[i+1][1]-pts[i][1])/dx[i]);
  t[0]=m[0];t[n-1]=m[n-2];
  for(i=1;i<n-1;i++)t[i]=(m[i-1]*m[i]<=0)?0:(m[i-1]+m[i])/2;
  for(i=0;i<n-1;i++){if(m[i]===0){t[i]=0;t[i+1]=0;continue;}
    var a=t[i]/m[i],b=t[i+1]/m[i],s=a*a+b*b;
    if(s>9){var f2=3/Math.sqrt(s);t[i]=f2*a*m[i];t[i+1]=f2*b*m[i];}}
  var d='M'+pts[0][0].toFixed(1)+' '+pts[0][1].toFixed(1);
  for(i=0;i<n-1;i++){var h=dx[i];
    d+=' C'+(pts[i][0]+h/3).toFixed(1)+' '+(pts[i][1]+t[i]*h/3).toFixed(1)
      +' '+(pts[i+1][0]-h/3).toFixed(1)+' '+(pts[i+1][1]-t[i+1]*h/3).toFixed(1)
      +' '+pts[i+1][0].toFixed(1)+' '+pts[i+1][1].toFixed(1);}
  return d;}
function curY(hist,v,hi){if(!(hi>0)||!hist.length)return 0;
  var pos=Math.min(hist.length-1,Math.max(0,v/hi*hist.length));
  var lo=Math.floor(pos),hi2=Math.min(hist.length-1,lo+1),f=pos-lo;
  return hist[lo]*(1-f)+hist[hi2]*f;}
function blend(hex,other,t){var a=hex.replace('#',''),b=other.replace('#',''),o=[];
  for(var i=0;i<3;i++){var c1=parseInt(a.substr(i*2,2),16),c2=parseInt(b.substr(i*2,2),16);
    o.push(Math.round(c1+(c2-c1)*t));}
  return '#'+o.map(function(v){return ('0'+Math.max(0,Math.min(255,v)).toString(16)).slice(-2);}).join('');}
function winLabel(){return dayMode?('指定日 '+dayKey)
  :(allMode?'全部日期'
  :(win?(win<=3?win+' 天':'近 '+win+' 天'):'自定义窗口'));}
function pal(mi){return PAL[mi]||'#5FC2A0';}
function plabel(pi){return PLAT[pi]||'';}
/* 「聚焦日」= 三档明细视图与 0—24 时「仅当日」的锚点日：
   指定日模式下所选的那天 > 自定义区间终点日 > 当日。
   日活分布、分布热力图的「当周 / 当月」都以此日所在自然周 / 自然月展开。 */
function focusDayKey(){return dayMode?dayKey:(cHi?fm(new Date(cHi*60000)):fm(todayDate()));}
function dayStartMin(k){return Math.floor(new Date(k+'T00:00:00').getTime()/60000);}
/* 近 N 天 = 含生成当日在内的 N 个自然日：[当日-(N-1)天 00:00, ∞)。
   右端保持开放，避免把当天晚些时候的请求排除掉。自定义窗口仍走 cLo/cHi。
   指定日模式优先级最高：[所选日 00:00, 次日 00:00)。 */
function cutLo(){return dayMode?dayStartMin(dayKey)
  :(allMode?dataMinMin:(win?dayAnchor-win*1440:(cLo||0)));}
function cutHi(){return dayMode?dayStartMin(dayKey)+1440
  :(allMode?Infinity:((!win&&cHi)?cHi:Infinity));}
function inWin(tsMin){return tsMin>=cutLo()&&tsMin<cutHi();}
function orderByTokens(A){return models.map(function(m,i){return i;})
  .filter(function(i){return A.mt[i]>0;})
  .sort(function(a,b){return A.mt[b]-A.mt[a];});}
/* 总量口径的模型排序：用于「累计」档与单次请求大小分布的 TOP 选取 */
function orderByTokensAll(A){return models.map(function(m,i){return i;})
  .filter(function(i){return A.mtAll[i]>0;})
  .sort(function(a,b){return A.mtAll[b]-A.mtAll[a];});}

/* ---------------- 聚合（与 Python 口径一致） ---------------- */
function aggregate(){
  var lo=cutLo(),hi=cutHi(),focusKey=focusDayKey();
  var A={tot:0,inp:0,out:0,ch:0,cw:0,turns:0,nsess:0,cost:0,totAll:0,
    daily:{},dailyAll:{},dm:{},mt:new Array(models.length).fill(0),
    mtAll:new Array(models.length).fill(0),
    /* thb = 仅「聚焦日」的按模型逐时消耗，供 0—24 时分布「仅当日」口径使用。
       指定日模式下聚焦日就是所选日，而非生成当日。
       hball = 全部数据（不限时间窗口，仅受平台筛选）的按模型逐时消耗，
       供 0—24 时分布「累计」口径使用。
       dailyAll / hmAll / wsAll / sessAll = 全量（总量口径）每日与逐时分布：
       分布热力图与日活分布一律按总量显示，不受顶部时间窗口影响。
       mtAll / sizesAll / allAll = 全量模型总量与单次请求大小：
       单次请求大小分布整卡、以及「累计」档的 TOP 模型排序都按总量口径。 */
    hball:{},thb:{},hm:{},hmAll:{},wsAll:{},sessAll:{},wsT:{},sessT:[],
    sizesAll:{},allAll:[],bands:[0,0,0,0],plats:{},dmAll:{},modelPlats:{}};
  for(var si=0;si<SESS.length;si++){
    var s=SESS[si];if(platFilter>=0&&s.p!==platFilter)continue;
    var sn=0,sessDay={};
    var tst=0,tsn=0,tfirst=0,tlast=0;
    for(var ri=0;ri<s.r.length;ri++){var r=s.r[ri];
      /* 总量口径不受时间窗口限制：先于窗口过滤累计全量逐时与全量每日分布 */
      var dA=new Date(r[0]*60000),dkA=fm(dA),hA=dA.getHours();
      A.totAll+=r[2];
      A.mtAll[r[1]]+=r[2];
      if(r[2]>0){(A.sizesAll[r[1]]=A.sizesAll[r[1]]||[]).push(r[2]);A.allAll.push(r[2]);}
      tst+=r[2];tsn++;if(!tfirst)tfirst=r[0];tlast=r[0];
      (A.hball[r[1]]=A.hball[r[1]]||new Array(24).fill(0))[hA]+=r[2];
      (A.dailyAll[dkA]=A.dailyAll[dkA]||{h:new Array(24).fill(0),tt:0});
      A.dailyAll[dkA].h[hA]+=r[2];A.dailyAll[dkA].tt+=r[2];
      (A.dmAll[dkA]=A.dmAll[dkA]||{})[r[1]]=(A.dmAll[dkA][r[1]]||0)+r[2];
      (A.hmAll[dkA]=A.hmAll[dkA]||new Array(24).fill(0))[hA]+=r[2];
      (sessDay[dkA]=sessDay[dkA]||new Array(24).fill(0))[hA]+=r[2];
      (A.wsAll[s.w]=A.wsAll[s.w]||{});
      (A.wsAll[s.w][dkA]=A.wsAll[s.w][dkA]||new Array(24).fill(0))[hA]+=r[2];
      if(r[0]<lo||r[0]>=hi)continue;
      var d=new Date(r[0]*60000),dk=fm(d),h=d.getHours();
      A.tot+=r[2];A.inp+=r[3];A.out+=r[4];A.ch+=r[5];A.cw+=r[6]||0;A.turns++;A.cost+=cost(r);
      A.plats[s.p]=1;
      (A.daily[dk]=A.daily[dk]||{h:new Array(24).fill(0),tt:0});
      A.daily[dk].h[h]+=r[2];A.daily[dk].tt+=r[2];
      (A.hm[dk]=A.hm[dk]||new Array(24).fill(0))[h]+=r[2];
      (A.dm[dk]=A.dm[dk]||{})[r[1]]=(A.dm[dk][r[1]]||0)+r[2];
      A.mt[r[1]]+=r[2];A.bands[Math.min(3,Math.floor(h/6))]+=r[2];
      (A.modelPlats[r[1]]=A.modelPlats[r[1]]||[]);if(A.modelPlats[r[1]].indexOf(s.p)<0)A.modelPlats[r[1]].push(s.p);
      if(dk===focusKey)(A.thb[r[1]]=A.thb[r[1]]||new Array(24).fill(0))[h]+=r[2];
      sn++;}
    if(sn)A.nsess++;
    /* 总量清单：工作空间与会话列表按全量口径统计，不受顶部时间窗口影响 */
    (A.wsT[s.w]=A.wsT[s.w]||{tt:0,cnt:0});A.wsT[s.w].tt+=tst;A.wsT[s.w].cnt++;
    A.sessT.push({i:si,s:s,rs:s.r,tt:tst,tn:tsn,first:tfirst,last:tlast});
    A.sessAll[si]=sessDay;
  }
  A.gp50All=pctile(A.allAll,50);
  A.costModel=new Array(models.length).fill(0);
  A.turnsPerModel=new Array(models.length).fill(0);
  for(var k=0;k<SESS.length;k++){
    if(platFilter>=0&&SESS[k].p!==platFilter)continue;
    for(var j=0;j<SESS[k].r.length;j++){
    var rr=SESS[k].r[j];if(!inWin(rr[0]))continue;
    A.costModel[rr[1]]+=cost(rr);A.turnsPerModel[rr[1]]++;}}
  return A;
}

/* ---------------- 跟随式 tooltip ---------------- */
var tip=document.getElementById('tip');
document.addEventListener('mousemove',function(ev){
  var t=ev.target,host=t&&t.closest?t.closest('[data-tip]'):null;
  if(host&&host.dataset.tip){tip.textContent=host.dataset.tip;tip.style.opacity=1;
    tip.style.left=Math.min(window.innerWidth-290,ev.clientX+14)+'px';
    tip.style.top=(ev.clientY+16)+'px';}
  /* #hourChart 内的悬停竖线有自己的分段 tooltip（在更早的冒泡阶段写入），
     document 级监听处于冒泡末端、最后执行，不能把它没看到的 hour 级 tooltip 盖回 0 */
  else if(!(hourCtx.length&&hourChartEl&&hourChartEl.contains(t)))tip.style.opacity=0;});

/* ---------------- 0—24 时分布：悬停竖线 + 该小时分模型消耗 ---------------- */
/* #hourChart 是常驻容器（每次重绘只替换 innerHTML），监听器用事件委托
   绑一次即可长期生效；竖线节点每次现查（renderHour 重绘会重建 DOM，
   缓存节点的引用会变成游离节点导致赋值失效）；hourCtx 由 renderHour 更新。 */
var hourCtx=[],hourChartEl=document.getElementById('hourChart');
var hxHide=function(){var l=hourChartEl&&hourChartEl.querySelector('.hxline');
  if(l)l.style.opacity=0;};
if(hourChartEl){
  hourChartEl.addEventListener('mousemove',function(ev){
    var svg=hourChartEl.querySelector('svg');
    var rc=svg&&hourCtx.length?svg.getBoundingClientRect():null;
    if(!rc||!rc.width){hxHide();return;}
    var xv=(ev.clientX-rc.left)/rc.width*24;
    if(xv<-0.6||xv>24.61){hxHide();return;}
    var h=Math.max(0,Math.min(23,Math.round(xv)));
    var line=hourChartEl.querySelector('.hxline');
    if(!line){var wrap=hourChartEl.querySelector('.hchart');
      if(!wrap){hxHide();return;}
      line=document.createElement('i');line.className='hxline';wrap.appendChild(line);}
    line.style.left=(h/24*100)+'%';line.style.opacity=1;
    var total=0,detail=[];
    hourCtx.forEach(function(m){var v=m.series[h]||0;total+=v;
      if(v>0)detail.push(m.name+'：'+fmt(v)+' token');});
    tip.textContent=(h<10?'0'+h:h)+':00–'+(h+1)+':00\n'
      +(detail.length?detail.join('\n'):'该时段无消耗')+'\n合计 '+fmt(total)+' token';
    tip.style.opacity=1;tip.style.left=Math.min(window.innerWidth-290,ev.clientX+14)+'px';
    tip.style.top=(ev.clientY+16)+'px';});
  hourChartEl.addEventListener('mouseleave',function(){hxHide();tip.style.opacity=0;});}

/* ---------------- 指标区块 ---------------- */
function renderHero(A){
  var order=orderByTokens(A);
  var top=order.length?order[0]:-1;
  var days=Object.keys(A.daily).length;
  var warn=dayMode&&!A.tot
    ?('指定日 '+dayKey+' 当日无请求 · 可用 ‹ › 切换日期，或从日历另选一天')
    :((!dayMode&&win&&days&&days<win)?('当前窗口为'+winLabel()+'，实际仅 '+days
      +' 天有数据 · 日均按有数据日计算，空窗不计入'):'');
  $('#heroMain').innerHTML=fmt(A.tot)+' Token&ensp;·&ensp;'+nf(A.turns)
    +' 次请求&ensp;·&ensp;预估 ¥'+A.cost.toFixed(2);
  $('#heroSub').innerHTML='缓存命中 '+pct(A.ch,A.inp).toFixed(1)+'%&ensp;·&ensp;主力模型 '
    +esc(top>=0?models[top]:'—')+' 占 '+pct(top>=0?A.mt[top]:0,A.tot).toFixed(1)
    +'%&ensp;·&ensp;覆盖 '+Object.keys(A.plats).length+' 个平台 / '+days+' 个有数据日';
  $('#heroWarn').innerHTML=esc(warn);
  $('#heroPrice').innerHTML='¥'+(A.tot?(A.cost/A.tot*1e6):0).toFixed(2)+' / 百万';
}
function renderKpis(A){
  var days=Object.keys(A.daily).length||1;
  $('#kpis').innerHTML=[
    ['合计 Token',fmt(A.tot),'',true],['请求轮次',nf(A.turns),'',false],
    ['缓存命中率',pct(A.ch,A.inp).toFixed(1),'%',false],
    ['预估金额（元）','¥'+A.cost.toFixed(2),'',false],
    ['日均（有数据天）',fmt(A.tot/days),'',false],['会话',nf(A.nsess),'',false],
    ['输入 / 输出比',(A.out?Math.round(A.inp/A.out):0)+' : 1','',false]]
    .map(function(x){return '<div class="kpi'+(x[3]?' emph':'')+'"><div class="k">'+x[0]
      +'</div><div class="v">'+x[1]+(x[2]?'<small>'+x[2]+'</small>':'')+'</div></div>';}).join('');
}

/* ---------------- 按模型消耗 ---------------- */
function modelRows(A){
  var order=orderByTokens(A);
  if(!order.length)return '<div class="cap">暂无数据</div>';
  var cap=A.mt[order[0]]||1,rows='';
  order.slice(0,8).forEach(function(mi){
    var dim=selModel!==null&&selModel!==mi;
    rows+='<div class="mrow'+(dim?' dim':'')+'"><span class="nm" data-dm="'+mi
      +'" title="点击聚焦该模型"><i class="dot" style="background:'+pal(mi)+'"></i>'+esc(models[mi])
      +'<span class="vendor">'+esc(VENDOR[mi]||'')+'</span></span>'
      +'<span class="track"><i style="width:'+pct(A.mt[mi],cap).toFixed(1)
      +'%;background:'+pal(mi)+'"></i></span>'
      +'<span class="num">'+fmt(A.mt[mi])+'&ensp;·&ensp;'+esc(VENDOR[mi]||'')+'&ensp;·&ensp;'
      +pct(A.mt[mi],A.tot).toFixed(1)+'%</span>'
      +'<span class="plats">'+((A.modelPlats[mi]||[]).map(function(pi){
        return '<i class="pchip">'+esc(plabel(pi))+'</i>';}).join(''))+'</span></div>';});
  /* 缓存命中率 / 输入·输出比已在 KPI 区呈现，这里不再重复画低区分度的进度条 */
  return rows;
}

/* ---------------- 每日堆叠柱 ---------------- */
/* 数据按总量口径（A.dmAll，全部扫描数据，不受顶部周期窗口影响）；
   dailySpan 仅决定「画哪一段」：1 / 3 / 7 个自然日 或 当月。 */
function dailyDays(A){
  var all=Object.keys(A.dmAll||{}).sort();
  if(!all.length)return [];
  var t=todayDate(),res;
  if(dailySpan==='month'){
    var lo=new Date(t.getFullYear(),t.getMonth(),1).getTime()/60000;
    res=all.filter(function(dk){return dayStartMin(dk)>=lo;});
  }else{
    var n=+dailySpan,base0=new Date(t.getTime()-(n-1)*86400000);
    var lo=dayStartMin(fm(base0));
    res=all.filter(function(dk){return dayStartMin(dk)>=lo;});
  }
  return res.length?res:all;   // 该跨度无数据则回退到全量，避免空白
}
function renderDaily(A){
  var days=dailyDays(A);
  if(!days.length){$('#dailyChart').innerHTML='<div class="cap">暂无数据</div>';return;}
  var order=orderByTokensAll(A);   // 总量口径排序，堆叠顺序跨跨度稳定
  var top=order.slice(0,6);
  if(selModel!==null&&top.indexOf(selModel)<0)top.push(selModel);
  var mx=1;
  days.forEach(function(dk){var t=0,o=A.dmAll[dk]||{};Object.keys(o).forEach(function(k){t+=o[k];});
    if(t>mx)mx=t;});
  var W=460,H=190,left=40,base=158,slot=(W-left-8)/days.length;
  var bw=Math.max(5,Math.min(34,slot*0.6));
  var out=['<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="每日模型用量堆叠柱图">',
    '<path d="M'+left+' 16H'+(W-4)+'M'+left+' '+base+'H'+(W-4)
    +'" stroke="var(--bd)" stroke-width="1" fill="none"/>',
    '<text x="2" y="20" fill="var(--t3)" font-size="9">'+fmt(mx)+'</text>',
    '<text x="2" y="'+(base+3)+'" fill="var(--t3)" font-size="9">0</text>'];
  days.forEach(function(dk,i){
    var x=left+i*slot+(slot-bw)/2,acc=0,parts=[];
    var o=A.dmAll[dk]||{};
    top.forEach(function(mi){if(o[mi])parts.push([mi,o[mi]]);});
    parts.sort(function(a,b){return b[1]-a[1];});
    var dayTot=parts.reduce(function(a,p){return a+p[1];},0);
    parts.forEach(function(pr){var mi=pr[0],v=pr[1],h=v/mx*(base-16),y=base-acc-h;
      var dim=selModel!==null&&selModel!==mi;
      out.push('<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+bw.toFixed(1)
        +'" height="'+Math.max(1,h).toFixed(1)+'" fill="'+pal(mi)+'" fill-opacity="'
        +(dim?0.25:0.92)+'" stroke="var(--bg)" stroke-width=".6"/>');
      acc+=h;});
    var dayTip=dk+' · 合计 '+nf(dayTot)+'\n'+parts.map(function(pr){
      return '· '+models[pr[0]]+'  '+nf(pr[1])+'（'+pct(pr[1],dayTot).toFixed(1)+'%）';}).join('\n');
    out.push('<rect x="'+(left+i*slot).toFixed(1)+'" y="16" width="'+slot.toFixed(1)
      +'" height="'+(base-16)+'" fill="#fff" fill-opacity="0" pointer-events="all" data-tip="'
      +esc(dayTip)+'"/>');
    var stepL=Math.max(1,Math.ceil(days.length/3));
    if(days.length<=4||i%stepL===0)out.push('<text x="'+(x+bw/2).toFixed(1)+'" y="'+(base+15)
      +'" fill="var(--t3)" font-size="9" text-anchor="middle">'+dk.slice(5)+'</text>');
  });
  out.push('</svg>');
  var legend=order.slice(0,6).map(function(mi){
    var dim=selModel!==null&&selModel!==mi;
    return '<span data-dm="'+mi+'"'+(dim?' style="opacity:.4"':'')
      +'><i style="background:'+pal(mi)+'"></i>'+esc(models[mi])+'</span>';}).join('');
  $('#dailyChart').innerHTML='<div class="legend">'+legend+'</div>'+out.join('');
}

/* ---------------- 单模型总量统计 ---------------- */
function renderModelTotals(A){
  var order=orderByTokens(A);
  if(!order.length){$('#mtCard').innerHTML=
    '<h3>单模型总量统计</h3><div class="cap">暂无数据</div>';return;}
  var isCost=document.body.dataset.metric==='cost';
  var rows=order.slice(0,8).map(function(mi){
    return '<tr><td style="color:var(--t1);font-weight:600"><i class="dot" style="background:'
      +pal(mi)+'"></i> '+esc(models[mi])+'</td>'
      +'<td class="num"><span class="v-token">'+fmt(A.mt[mi])+'</span><span class="v-cost">¥'
      +A.costModel[mi].toFixed(2)+'</span></td>'
      +'<td class="mono">'+nf(A.turnsPerModel[mi])+'</td>'
      +'<td class="num" style="color:var(--brandb)"><span class="v-token">'
      +pct(A.mt[mi],A.tot).toFixed(1)+'%</span><span class="v-cost">'
      +pct(A.costModel[mi],A.cost).toFixed(1)+'%</span></td></tr>';});
  rows.push('<tr class="total"><td>合计</td><td class="num"><span class="v-token">'+fmt(A.tot)
    +'</span><span class="v-cost">¥'+A.cost.toFixed(2)+'</span></td><td class="mono">'
    +nf(A.turns)+'</td><td class="num"><span class="v-token">100%</span>'
    +'<span class="v-cost">100%</span></td></tr>');
  $('#mtCard').innerHTML=
    '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><h3>单模型总量统计</h3>'
    +'<div class="seg" id="metricSeg" role="group" aria-label="显示口径切换">'
    +'<button type="button" class="'+(isCost?'':'on')+'" data-metric-opt="token">按 Token</button>'
    +'<button type="button" class="'+(isCost?'on':'')
    +'" data-metric-opt="cost">按金额</button></div>'
    +'<span class="hdnote" style="margin-left:auto">周期跟随全局时间窗口 · 当前 '
    +esc(winLabel())+'</span></div>'
    +'<div class="cap">「按 Token / 按金额」可切换显示口径 · 金额按牌价与摊算规则估算 · '
    +'缓存写入按 1.25× 输入价 · 单价与汇率详见口径页</div>'
    +'<table><thead><tr><th>模型</th>'
    +'<th><span class="v-token">Token 总量</span><span class="v-cost">预估金额（元）</span></th>'
    +'<th>请求次数</th><th><span class="v-token">Token 占比</span>'
    +'<span class="v-cost">金额占比</span></th></tr></thead><tbody>'+rows.join('')+'</tbody></table>';
  var seg=document.getElementById('metricSeg');
  if(seg)seg.addEventListener('click',function(ev){
    var opt=ev.target.closest('[data-metric-opt]');if(!opt)return;
    document.body.dataset.metric=opt.getAttribute('data-metric-opt');
    [].forEach.call(seg.querySelectorAll('[data-metric-opt]'),function(x){
      x.classList.toggle('on',x===opt);});});
}

/* ---------------- 0—24 时分布 ---------------- */
function renderHour(A){
  var isToday=hourMode==='today',dayStr=focusDayKey();
  var src=isToday?A.thb:A.hball;
  var hn=$('#hourNote'),hs=$('#hourSub');
  function sum(s){return s?s.reduce(function(a,b){return a+b;},0):0;}
  /* 仅当日按当日消耗重选排序，避免「今天活跃的模型」被全量总量挤掉；
     曲线数量由页面 #hourTop 下拉控制（TOP 3 / 5 / 10 / 全部，0=全部）。 */
  var order=isToday
    ?models.map(function(m,i){return i;}).filter(function(i){return sum(src[i])>0;})
       .sort(function(a,b){return sum(src[b])-sum(src[a]);})
    :orderByTokensAll(A);   // 累计档：TOP 模型按全量总量排序，不受时间窗口影响
  var top=hourTop>0?order.slice(0,hourTop):order;
  if(hn)hn.textContent=isToday
    ?('仅 '+dayStr+' 当日 · 0—23 时逐时消耗（尚未到的时段为 0）')
    :'全部数据累计 · 0—23 时同一时段跨日累加（不限时间窗口）';
  if(hs)hs.textContent=(isToday
    ?'每条曲线 = 当日该时段的实际消耗 · 未来时段为 0'
    :'每条曲线 = 全部数据在该时段的消耗总和（不限时间窗口）')
    +' · 点击图例聚焦单个模型 · 悬浮看该小时各模型消耗'
    +(top.length?' · 当前显示 '+(hourTop>0?'TOP ':'全部 ')+top.length+' 模型':'');
  if(!top.length){$('#hourChart').innerHTML='<div class="cap">'
    +(isToday||dayMode?dayStr+' 当日暂无请求（可另选日期或切回周期窗口）':'暂无数据')+'</div>';
    hourCtx=[];return;}
  hourCtx=top.map(function(mi){return {name:models[mi],vendor:VENDOR[mi]||'',
    series:(src[mi]||new Array(24).fill(0)).slice()};});
  var W=1240,base=150;
  var peak=niceMax(Math.max.apply(null,top.map(function(mi){
    return Math.max.apply(null,src[mi]||new Array(24).fill(0));})));
  var step=W/24,out=['<svg viewBox="0 0 '+W+' '+(base+34)
    +'" role="img" aria-label="0—24 时按模型分布">'];
  [0.2,0.55].forEach(function(fr){var y=base-fr*(base-12);
    out.push('<line x1="0" y1="'+y.toFixed(1)+'" x2="'+W+'" y2="'+y.toFixed(1)
      +'" stroke="var(--bd)" stroke-width="1"/>');
    out.push('<text x="2" y="'+(y-5).toFixed(1)+'" fill="var(--t3)" font-size="10">'
      +fmt(peak*fr)+'</text>');});
  out.push('<line x1="0" y1="'+base+'" x2="'+W+'" y2="'+base
    +'" stroke="var(--bds)" stroke-width="1"/>');
  top.forEach(function(mi,i){
    var series=src[mi]||new Array(24).fill(0);
    var pts=series.map(function(v,h){return [h*step,base-v/peak*(base-12)];});
    var line=smoothLine(pts);
    var dim=selModel!==null&&selModel!==mi;
    out.push('<g opacity="'+(dim?0.25:1)+'">'
      +'<path d="'+line+' L'+W+','+base+' L0,'+base+' Z" fill="'+pal(mi)
      +'" fill-opacity="'+(i===0?0.16:0.12)+'" stroke="none"/>'
      +'<path d="'+line+'" fill="none" stroke="'+pal(mi)+'" stroke-width="2"/>'
      +'<path d="'+line+'" fill="none" stroke="rgba(0,0,0,0)" stroke-width="8" data-tip="'
      +esc(models[mi]+'\n'+((isToday||dayMode)?'当日':'24h')
      +' 合计 '+fmt(sum(series))+' token')+'"/></g>');});
  for(var h=0;h<24;h+=2)out.push('<text x="'+(h*step+6).toFixed(1)+'" y="'+(base+22)
    +'" fill="var(--t3)" font-size="10">'+h+'时</text>');
  out.push('</svg>');
  var legend=top.map(function(mi){var dim=selModel!==null&&selModel!==mi;
    return '<span data-dm="'+mi+'"'+(dim?' style="opacity:.4"':'')
      +'><i style="background:'+pal(mi)+'"></i>'+esc(models[mi])+' · '
      +esc(VENDOR[mi]||'')+'</span>';}).join('');
  $('#hourChart').innerHTML='<div class="legend" style="justify-content:flex-end">'
    +legend+'</div>'+'<div class="hchart">'+out.join('')+'<i class="hxline"></i></div>';
}

/* ---------------- 单次请求大小分布 ---------------- */
function renderDist(A){
  var order=models.map(function(m,i){return i;})
    .filter(function(i){return A.sizesAll[i]&&A.sizesAll[i].length;})
    .sort(function(a,b){return A.mtAll[b]-A.mtAll[a];});
  var top=distTop>0?order.slice(0,distTop):order;
  if(!top.length){$('#distBody').innerHTML='<div class="cap">暂无数据</div>';
    $('#distNote').textContent='';return;}
  $('#distNote').textContent=(distTop>0?'TOP '+top.length:'全部 '+top.length)
    +' 模型 · 共 '+nf(top.reduce(function(a,mi){return a+A.sizesAll[mi].length;},0))
    +' 次 · 总量口径（不限时间窗口）';
  var cap90=Math.max.apply(null,top.map(function(mi){return pctile(A.sizesAll[mi],90);}))||1;
  var head='<div class="dhead drow" style="border-bottom:1px solid var(--bd)"><span>模型</span>'
    +'<span>次数</span><span>50%</span><span>90%</span></div>';
  var left=top.map(function(mi){
    var s50=pctile(A.sizesAll[mi],50),s90=pctile(A.sizesAll[mi],90);
    function cell(v,is90){var c=is90?blend(pal(mi),'#FFFFFF',0.45):pal(mi);
      return '<span class="val">'+fmt(v)+'<small>'+(is90?'90%':'50%')
        +'<i style="width:'+pct(v,cap90).toFixed(1)+'%;background:'+c+'"></i></small></span>';}
    return '<div class="drow"><span class="nm">'+esc(models[mi])+'</span><span class="val">'
      +nf(A.sizesAll[mi].length)+'</span>'+cell(s50,false)+cell(s90,true)+'</div>';}).join('');
  var hi=niceMax(cap90*1.35),K=36,width=860,base=150,step=width/K;
  var svg=['<svg viewBox="0 0 '+width+' '+(base+26)
    +'" role="img" aria-label="单次请求大小分布">'];
  svg.push('<line x1="0" y1="'+base+'" x2="'+width+'" y2="'+base
    +'" stroke="var(--bds)" stroke-width="1"/>');
  top.forEach(function(mi){
    var hist=new Array(K).fill(0);
    A.sizesAll[mi].forEach(function(v){hist[Math.min(K-1,Math.floor(v/hi*K))]++;});
    var pk=Math.max.apply(null,hist)||1;
    var sm=hist.map(function(v,i){return ((hist[i-1]||0)+2*v+(hist[i+1]||0))/4/pk;});
    var pts=sm.map(function(v,i){return [i*step+step/2,base-v*(base-16)];});
    var line=smoothLine(pts);
    var dim=selModel!==null&&selModel!==mi;
    var s50=pctile(A.sizesAll[mi],50),s90=pctile(A.sizesAll[mi],90);
    var tipTxt=esc(models[mi]+'\n'+nf(A.sizesAll[mi].length)+' 次 · 50% '+fmt(s50)+' · 90% '+fmt(s90));
    var p90x=(s90/hi*width).toFixed(1),p90y=(base-curY(sm,s90,hi)*(base-16)).toFixed(1);
    var p90Tip=esc(models[mi]+'\n90% 的请求单次 ≤ '+fmt(s90)+' token\n'
      +'共 '+nf(A.sizesAll[mi].length)+' 次 · 50% '+fmt(s50)+' token');
    svg.push('<g opacity="'+(dim?0.25:1)+'">'
      +'<path d="'+line+' L'+width+','+base+' L0,'+base+' Z" fill="'+pal(mi)
      +'" fill-opacity="0.14"/>'
      +'<path d="'+line+'" fill="none" stroke="'+pal(mi)+'" stroke-width="2"/>'
      +'<line x1="'+(s50/hi*width).toFixed(1)+'" y1="26" x2="'+(s50/hi*width).toFixed(1)
      +'" y2="'+base+'" stroke="'+pal(mi)+'" stroke-width="1.5" stroke-opacity=".8"/>'
      +'<path d="'+line+'" fill="none" stroke="rgba(0,0,0,0)" stroke-width="8" data-tip="'
      +tipTxt+'"/>'
      /* p90 点跟随模型色 + 白描边，单独置于上层；透明大圆扩大命中区并给出专属说明 */
      +'<circle cx="'+p90x+'" cy="'+p90y+'" r="4" fill="'+pal(mi)
      +'" stroke="#fff" stroke-width="1.5"/>'
      +'<circle cx="'+p90x+'" cy="'+p90y+'" r="11" fill="transparent" pointer-events="all" '
      +'data-tip="'+p90Tip+'"/></g>');});
  var gx=A.gp50All/hi*width;
  svg.push('<line x1="'+gx.toFixed(1)+'" y1="14" x2="'+gx.toFixed(1)+'" y2="'+base
    +'" stroke="var(--t3)" stroke-width="1" stroke-dasharray="4 4"/>');
  svg.push('<text x="'+Math.min(width-4,gx+6).toFixed(1)+'" y="24" fill="var(--t3)" '
    +'font-size="10">全局 50% '+fmt(A.gp50All)+'</text>');
  [0,1/3,2/3,1].forEach(function(fr){
    svg.push('<text x="'+(width*fr).toFixed(1)+'" y="'+(base+20)+'" fill="var(--t3)" '
      +'font-size="10"'+(fr===1?' text-anchor="end"':'')+'>'+(fr===0?'0':fmt(hi*fr))+'</text>');});
  svg.push('</svg>');
  $('#distBody').innerHTML='<div class="distwrap"><div>'+head+left+'</div><div>'+svg.join('')
    +'<div class="cap" style="margin-top:8px">每模型一条分布形状（各自归一）· '
    +'实线=该模型 50% · 同色圆点=该模型 90%（悬浮看数值）· 虚线=全局 50% · '
    +'数值下条形=两列共享刻度的大小对比（深=50% 浅=90%）</div></div></div>';
}

/* ---------------- 日活热力 ---------------- */
function renderHeat(A){
  var dayKeys=Object.keys(A.daily).sort();
  var views=[['day','日'],['week','周'],['month','月']];
  var seg='<div class="seg">'+views.map(function(v){
    return '<button type="button" class="'+(heatView===v[0]?'on':'')
      +'" data-hv="'+v[0]+'">'+v[1]+'</button>';}).join('')+'</div>';
  if(!dayKeys.length){$('#dayhourCard').innerHTML=
    '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><h3>日活分布</h3>'
    +seg+'</div><div class="cap">该时间范围内无数据</div>';return;}
  /* 序列锚点跟随全局时间选择：指定日 → 所选日；自定义区间 → 区间终点日；
     周期/总量窗口 → 窗口内最晚有数据日（上限为生成当日）。切换时间选择时，
     日/周/月三档明细会重新定位到对应日所在的日/周/月。 */
  var anchor=new Date(focusDayKey()+'T00:00:00');
  function daySeq(n){var out=[];
    for(var i=n-1;i>=0;i--)out.push(fm(new Date(anchor.getTime()-i*86400e3)));
    return out;}
  /* 月视图 = 锚点所在自然月的 1 日 → 月末（而非从今天倒推 30 天）。
     尚未到达的日期画成虚线空格，明确留空、不参与占比与色阶计算。 */
  function monthDays(a){return new Date(a.getFullYear(),a.getMonth()+1,0).getDate();}
  function monthSeq(a){var y=a.getFullYear(),m=a.getMonth(),out=[];
    for(var d=1;d<=monthDays(a);d++)out.push(fm(new Date(y,m,d)));
    return out;}
  /* 时段占比取锚点当日全量逐时（与「日」档同一口径） */
  var focusH=(A.dailyAll[focusDayKey()]?A.dailyAll[focusDayKey()].h:new Array(24).fill(0));
  var bands=[0,0,0,0];
  for(var bi=0;bi<24;bi++)bands[Math.min(3,Math.floor(bi/6))]+=focusH[bi];
  var bandTotal=bands.reduce(function(a,b){return a+b;},0)||1;
  var names=['凌晨 0—6','上午 6—12','下午 12—18','晚间 18—24'];
  var chips='<div class="chips">'+bands.map(function(v,i){
    return '<div class="chip2"><span>'+names[i]+'</span><b>'
      +pct(v,bandTotal).toFixed(1)+'%</b></div>';}).join('')+'</div>';
  var scope=dayMode?('指定日 '+dayKey+' · '):'';
  var note=scope+(heatView==='day'?'仅当日一行 · 每格一小时 · 悬浮看数值'
    :heatView==='week'?'当周 7 个自然日（周一至周日）· 每格一天的消耗 · 悬浮看数值'
    :'本月 1 日起共 '+monthDays(anchor)+' 天 · 每格一天的消耗 · 未来日期留空 · 悬浮看数值');
  var head='<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><h3>日活分布</h3>'
    +seg+'<span class="hdnote" style="margin-left:auto">'+esc(note)+'</span></div>';
  var sw=HEAT.map(function(c){return '<i style="background:'+c+'"></i>';}).join('');
  var legend='<div class="hmlegend">低 '+sw+' 高</div>';
  var body='';
  if(heatView==='day'){
    /* 日档只显示当日一行（锚点日 = 指定日 / 自定义终点 / 当日），其余日期不渲染 */
    var days=[focusDayKey()],peak=1;
    days.forEach(function(dk){(A.hmAll[dk]||[]).forEach(function(v){if(v>peak)peak=v;});});
    /* 日期文字与热力格必须放进同一张 SVG 整体缩放：旧版日期是固定高度的
       HTML 标签列，而 SVG 自适应容器宽度整体缩放，两套行距缩放比例不同，
       行数一多日期就漂移错位 */
    var cell=40,gap=6,labelW=80,rowH=16,rowGap=8,top=22;
    var width=labelW+24*(cell+gap),height=top+days.length*(rowH+rowGap)+2;
    var svg=['<svg viewBox="0 0 '+width+' '+height
      +'" role="img" aria-label="日 × 小时热力图">'];
    for(var h=0;h<24;h++)svg.push('<text x="'+(labelW+h*(cell+gap)+cell/2)+'" y="12" '
      +'fill="var(--t3)" font-size="9" text-anchor="middle">'+h+'</text>');
    days.forEach(function(dk,r){var y=top+r*(rowH+rowGap);
      var has=!!A.dailyAll[dk],dayTot=has?A.dailyAll[dk].tt:0;
      svg.push('<text x="'+(labelW-8)+'" y="'+(y+rowH/2+3.5).toFixed(1)+'" fill="'
        +(has?'var(--t2)':'var(--t3)')+'" font-size="10" text-anchor="end"'
        +' style="font-family:var(--mono)">'+esc(dk.slice(5).replace('-','—'))+'</text>');
      for(var hh=0;hh<24;hh++){var v=(A.hmAll[dk]||new Array(24).fill(0))[hh];
        var lv=v<=0?0:Math.min(HEAT.length-1,1+Math.floor(v/peak*5.999));
        svg.push('<rect x="'+(labelW+hh*(cell+gap))+'" y="'+y+'" width="'+cell+'" height="'+rowH
          +'" rx="3" fill="'+(v>0?HEAT[lv]:'var(--surface2)')+'" data-tip="'+esc(dk+' '+hh+':00–'+(hh+1)
          +':00\n'+nf(v)+' token（占当日 '+pct(v,dayTot).toFixed(1)+'%）')+'"/>');}});
    svg.push('</svg>');
    body=svg.join('');
  }else{
    var seq=heatView==='week'?weekSeq(anchor):monthSeq(anchor);
    var n=seq.length,anchorKey=fm(anchor);
    /* 「尚未到达」只相对生成当日。指定日若选历史某天，不能把该月里所选日
       之后的已过日期误判成未来空格（常规/自定义模式下 horizonKey === anchorKey）。 */
    var horizonKey=dayMode?fm(todayDate()):anchorKey;
    var shareLabel=heatView==='week'?'当周':'当月';
    var total=0,peak=1;
    seq.forEach(function(dk){
      if(dk>horizonKey)return;              // 未到达的日期不参与占比与色阶
      var v=A.dailyAll[dk]?A.dailyAll[dk].tt:0;
      total+=v;if(v>peak)peak=v;});
    total=total||1;
    var cw=heatView==='week'?132:34,g=heatView==='week'?12:6;
    var width=n*(cw+g)-g,H=heatView==='week'?78:56;
    var svg=['<svg viewBox="0 0 '+width+' '+H+'" role="img" aria-label="'
      +(heatView==='week'?'当周 7 天每日消耗':'当月 1 日起每日消耗')+'">'];
    seq.forEach(function(dk,i){
      var future=dk>horizonKey;
      var v=future?0:(A.dailyAll[dk]?A.dailyAll[dk].tt:0);
      var lv=v<=0?0:Math.min(HEAT.length-1,1+Math.floor(v/peak*5.999));
      var x=i*(cw+g),ch=heatView==='week'?44:30,y=heatView==='week'?24:8;
      if(future){
        svg.push('<rect x="'+x+'" y="'+y+'" width="'+cw+'" height="'+ch+'" rx="6" '
          +'fill="none" stroke="var(--bd)" stroke-width="1" stroke-dasharray="3 3" '
          +'opacity=".7" data-tip="'+esc(dk+'\n尚未到达')+'"/>');
      }else{
        svg.push('<rect x="'+x+'" y="'+y+'" width="'+cw+'" height="'+ch+'" rx="6" fill="'
          +(v>0?HEAT[lv]:'var(--surface2)')+'" data-tip="'+esc(dk+'\n'+nf(v)+' token（占'+shareLabel+' '
          +pct(v,total).toFixed(1)+'%）')+'"/>');
      }
      if(heatView==='week'){
        svg.push('<text x="'+(x+cw/2)+'" y="14" fill="var(--t3)" font-size="9.5" '
          +'text-anchor="middle">'+esc(dk.slice(5))+'</text>');
        if(v>0)svg.push('<text x="'+(x+cw/2)+'" y="'+(y+ch/2+4)+'" fill="var(--t1)" '
          +'font-size="10.5" font-weight="700" text-anchor="middle">'+fmt(v)+'</text>');
      }else if(i%5===0||i===n-1){
        svg.push('<text x="'+(x+cw/2)+'" y="'+(H-2)+'" fill="var(--t3)" font-size="8.5" '
          +'text-anchor="middle">'+esc(dk.slice(5))+'</text>');
      }});
    svg.push('</svg>');
    body=svg.join('');
  }
  $('#dayhourCard').innerHTML=head+chips+legend+body;
}

/* ---------------- 工作空间 / 下钻 ---------------- */
/* 对数色阶：档位上限跟随色板长度（HEAT.length-1），避免取到 undefined 颜色
   —— 那会让「有数据」的格子变透明，看起来像少画了几格 */
function heatLevel(v,avg){if(v<=0)return 0;
  var top=Math.max(1,HEAT.length-1);
  return Math.min(top,Math.max(1,1+Math.floor(Math.log(v/avg/0.001)/Math.log(350)*7)));}
/* 自然周序列：a 所在自然周的 7 天（周一 → 周日），跨月自动接续。 */
function weekSeq(a){
  var y=a.getFullYear(),m=a.getMonth(),d=a.getDate()-((a.getDay()+6)%7);
  var mon=new Date(y,m,d),out=[];
  for(var i=0;i<7;i++)out.push(fm(new Date(mon.getFullYear(),mon.getMonth(),mon.getDate()+i)));
  return out;}
/* 分布列粒度：day=当日 24 格（逐时）/ week=当周 7 天（每天 1 格）/ month=当月天数格。
   三档一律按「总量」时间周期显示，不受顶部时间窗口影响；
   锚点日 = 指定日 > 自定义区间终点 > 当日。 */
function granSpec(A){
  var a=new Date(focusDayKey()+'T00:00:00');
  if(wsGran==='day')return {list:[fm(a)],hourly:true,label:'日 · 24 时'};
  if(wsGran==='week')return {list:weekSeq(a),hourly:false,label:'周 · 当周 7 天'};
  var y=a.getFullYear(),m=a.getMonth(),n=new Date(y,m+1,0).getDate(),out=[];
  for(var d=1;d<=n;d++)out.push(fm(new Date(y,m,d)));
  return {list:out,hourly:false,label:'月 · 当月'};
}
/* 三档粒度共用 heatLevel 对数色阶，avg 按粒度校准：让「全局平均格子」都落在
   比值 ≈0.33（与旧版 3X 的视觉档次一致），避免天格/小时格全顶格或全空色 */
function granAvg(avgD){return wsGran==='day'?avgD/8:avgD*3;}
function vizCellsG(perDay,spec,avg){var todayK=fm(todayDate()),h='';
  /* 空格子用中性底色（--surface2）占位，保证整条格数看得清；只有有数据的格子才上色阶 */
  spec.list.forEach(function(dk){var arr=perDay[dk]||[],fut=dk>todayK;
    if(spec.hourly){
      for(var hh=0;hh<24;hh++){var v=arr[hh]||0;
        h+='<i style="background:'+(v>0?HEAT[heatLevel(v,avg)]:'var(--surface2)')+'" title="'
          +esc(dk+' '+hh+':00–'+(hh+1)+':00 · '+(fut?'尚未到达':fmt(v)))+'"></i>';}}
    else{var v=0;for(var i=0;i<24;i++)v+=arr[i]||0;
      h+='<i style="background:'+(v>0?HEAT[heatLevel(v,avg)]:'var(--surface2)')+'" title="'
        +esc(dk+' · '+(fut?'尚未到达':fmt(v)))+'"></i>';}});
  return h;}
function shdCells(entry,spec,avg,A){
  /* 会话行分布同样按总量口径：取该会话的全量逐时分布 */
  return vizCellsG((A&&A.sessAll[entry.i])||{},spec,avg);}
function pchips(ps){return ps.map(function(p){
  return '<span class="pchip">'+esc(PLAT[p]||'')+'</span>';}).join('');}
function rowHtml(attrs,nm,plat,tk,share,sub,viz){
  return '<div class="wsrow click" '+attrs+'><span class="nm" title="'+esc(nm)+'">'
    +esc(nm)+'</span><span class="wplat">'+plat+'</span><span class="tk">'+fmt(tk)
    +'</span><span class="sh">'+share+'<small>· '+sub+'</small></span>'
    +'<span class="wviz">'+viz+'</span><span class="chev">›</span></div>';}
/* 工作空间榜计数提示：搜索态显示匹配数且不受 TOP 限制，避免榜外项搜不到 */
function setWsNote(total,label){
  var n=$('#wsNote');if(!n)return;
  n.textContent=(q?('匹配 '+nf(total)+' 个'+label+' · 搜索结果全部显示')
    :('共 '+nf(total)+' 个'+label+(wsTop?' · 显示前 '+Math.min(wsTop,total)+' 个':' · 全部显示')))
    +' · 分布列按总量统计';
}
function showWsCtrls(on){
  var n=$('#wsNote'),s=$('#wsTop');
  if(n)n.style.display=on?'':'none';
  if(s)s.style.display=on?'':'none';
}
function renderPanel(A){
  var panel=$('#wsPanel'),crumb=$('#wsCrumb'),tools=$('#wsTools');
  /* 列表态限高滚动；会话详情自带散点/明细表滚动区，去掉限高避免嵌套滚动 */
  if(panel)panel.classList.add('scrollbox');
  /* 分布列一律按「总量」统计：色阶基准取全量日均，不随顶部时间窗口变化 */
  var avgD=A.totAll/(Object.keys(A.dailyAll).length||1);if(!(avgD>0))avgD=1;
  var spec=granSpec(A),avgG=granAvg(avgD);
  /* 每个工作空间涉及的平台（总量口径），供行内平台列使用 */
  var wplats={};
  A.sessT.forEach(function(x){(wplats[x.s.w]=wplats[x.s.w]||{})[x.s.p]=1;});
  if(state.ws===null){
    crumb.style.display='none';tools.style.display='block';showWsCtrls(true);
    $('#wsTitle').textContent='工作空间 & 会话消耗活跃分布';
    if(wsMode==='ses'){
      var srAll=A.sessT.filter(function(x){return !q||(x.s.t||'').toLowerCase().indexOf(q)>=0;})
        .sort(function(a,b){return b.tt-a.tt;});
      setWsNote(srAll.length,'会话');
      var sr=(q||!wsTop)?srAll:srAll.slice(0,wsTop);
      if(!sr.length){panel.innerHTML='<div class="cap">无匹配的会话</div>';return;}
      panel.innerHTML='<div class="wshead"><span>会话</span><span>平台</span><span>Token</span>'
        +'<span>占比 / 轮次</span><span>分布（'+spec.label+'）</span><span></span></div>'
        +sr.map(function(x){return rowHtml('data-si="'+x.i+'" data-tokens="'+x.tt
          +'" data-sessions="'+x.tn+'" data-name="'+esc((x.s.t||'').toLowerCase())+'"',
          x.s.t,pchips([x.s.p]),x.tt,pct(x.tt,A.totAll).toFixed(1)+'%',x.tn+' 轮',shdCells(x,spec,avgG,A));}).join('');
      return;}
    var order=Object.keys(A.wsT).map(Number).filter(function(w){return A.wsT[w].tt>0;});
    order.sort(function(a,b){return wsSort==='tokens'
      ?A.wsT[b].tt-A.wsT[a].tt:(A.wsT[b].cnt||0)-(A.wsT[a].cnt||0);});
    if(q)order=order.filter(function(w){return WS[w].toLowerCase().indexOf(q)>=0;});
    setWsNote(order.length,'工作空间');
    if(!q&&wsTop)order=order.slice(0,wsTop);
    if(!order.length){panel.innerHTML='<div class="cap">无匹配的工作空间</div>';return;}
    panel.innerHTML='<div class="wshead"><span>工作空间</span><span>平台</span><span>Token</span>'
      +'<span>占比 / 会话</span><span>分布（'+spec.label+'）</span><span></span></div>'
      +order.map(function(w){return rowHtml('data-ws="'+w+'" data-tokens="'+A.wsT[w].tt
        +'" data-sessions="'+(A.wsT[w].cnt||0)+'" data-name="'+esc(WS[w].toLowerCase())+'"',
        WS[w],pchips(Object.keys(wplats[w]||{}).map(Number).sort(function(a,b){return a-b;})),
        A.wsT[w].tt,pct(A.wsT[w].tt,A.totAll).toFixed(1)+'%',(A.wsT[w].cnt||0)+' 会话',
        vizCellsG(A.wsAll[w]||{},spec,avgG));}).join('');
    return;}
  showWsCtrls(false);   // 下钻到会话列表/详情时隐藏 TOP 控件与计数
  var entry=null;
  if(state.ses!==null)for(var ei=0;ei<A.sessT.length;ei++){
    if(A.sessT[ei].i===state.ses){entry=A.sessT[ei];break;}}
  if(state.ses===null||!entry){
    crumb.innerHTML='<button class="chip on" data-a="root">← 返回列表</button>'
      +'<span class="path"><span class="cur">'+esc(WS[state.ws])+'</span></span>';
    crumb.style.display='flex';tools.style.display='none';
    $('#wsTitle').textContent=WS[state.ws]+' · 会话列表';
    var arr=A.sessT.filter(function(x){return x.s.w===state.ws;})
      .sort(function(a,b){return b.tt-a.tt;});
    if(!arr.length){panel.innerHTML='<div class="cap">该工作空间暂无会话</div>';return;}
    panel.innerHTML=arr.map(function(x){return rowHtml('data-si="'+x.i
      +'" data-tokens="'+x.tt+'" data-sessions="'+x.tn
      +'" data-name="'+esc((x.s.t||'').toLowerCase())+'"',
      x.s.t,pchips([x.s.p]),x.tt,pct(x.tt,A.totAll).toFixed(1)+'%',x.tn+' 轮',shdCells(x,spec,avgG,A));}).join('');
    return;}
  var s=entry;
  if(panel)panel.classList.remove('scrollbox');
  crumb.innerHTML='<button class="chip on" data-a="up">← 返回</button>'
    +'<span class="path"><a data-a="root" style="cursor:pointer;'
    +'text-decoration:underline dotted">'+esc(WS[state.ws])+'</a>'
    +'<span class="sep">›</span><span class="cur">'+esc(s.s.t)+'</span></span>';
  crumb.style.display='flex';tools.style.display='none';
  $('#wsTitle').textContent='会话详情';
  panel.innerHTML='<div class="view-h"><div><div class="view-t">'+esc(s.s.t)+'</div>'
    +'<div class="view-m">'+esc(plabel(s.s.p))+' · '+esc(WS[state.ws])
    +' · '+fd(new Date(s.first*60000))+' '+ft(new Date(s.first*60000))
    +' → '+fd(new Date(s.last*60000))+' '+ft(new Date(s.last*60000))
    +' · '+nf(s.rs.length)+' 次请求 · 合计 '+fmt(s.tt)+'</div></div>'
    +'<div><button class="mini on" data-v="sc">散点</button> '
    +'<button class="mini" data-v="tb">明细表</button></div></div><div id="reqView"></div>';
  drawScatter(s);
  var bv=panel.querySelector('[data-v="sc"]'),bt=panel.querySelector('[data-v="tb"]');
  function setV(v){[bv,bt].forEach(function(b){
    b.classList.toggle('on',b.getAttribute('data-v')===v);});}
  if(bv)bv.onclick=function(){drawScatter(s);setV('sc');};
  if(bt)bt.onclick=function(){drawTable(s);setV('tb');};
}
function drawScatter(s){
  var el=$('#reqView');if(!el)return;
  var reqs=s.rs;
  if(!reqs.length){el.innerHTML='<div class="cap">暂无数据</div>';return;}
  var W=Math.max(420,el.clientWidth||560),H=250,pL=46,pR=12,pT=12,pB=26;
  var t0=reqs[0][0],t1=reqs[reqs.length-1][0],span=Math.max(1,t1-t0);
  var mx=1;reqs.forEach(function(r){if(r[2]>mx)mx=r[2];});
  function X(v){return pL+(W-pL-pR)*(v-t0)/span;}
  function Y(v){return pT+(H-pT-pB)*(1-Math.log(v+1)/Math.log(mx+1));}
  var g='';for(var i=0;i<4;i++){var yy=pT+(H-pT-pB)*i/3;
    g+='<line x1="'+pL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-pR)+'" y2="'+yy.toFixed(1)
    +'" stroke="var(--bd)"/>';}
  var pts='';reqs.forEach(function(r){var d=new Date(r[0]*60000);
    var tipTxt=fd(d)+' '+ft(d)+':'+String(d.getSeconds()).padStart(2,'0')+'\n'+models[r[1]]
      +'\n输入 '+nf(r[3])+' · 输出 '+nf(r[4])+'\n缓存 '+nf(r[5])+' · 合计 '+nf(r[2]);
    pts+='<circle cx="'+X(r[0]).toFixed(1)+'" cy="'+Y(r[2]).toFixed(1)+'" r="3.2" fill="'
      +pal(r[1])+'" fill-opacity=".82" data-tip="'+esc(tipTxt)+'"/>';});
  var d0=new Date(t0*60000),d1=new Date(t1*60000);
  el.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" width="100%"><g>'+g+pts
    +'<text x="'+pL+'" y="'+(pT+8)+'" font-size="9" fill="var(--t3)">'+fmt(mx)+'</text>'
    +'<text x="'+pL+'" y="'+(H-6)+'" font-size="9" fill="var(--t3)">'+fd(d0)+' '+ft(d0)+'</text>'
    +'<text x="'+(W-pR)+'" y="'+(H-6)+'" font-size="9" fill="var(--t3)" text-anchor="end">'
    +fd(d1)+' '+ft(d1)+'</text></g></svg>'
    +'<div style="margin-top:6px;font-size:10px;color:var(--t3)">x=时间 · y=单次请求 token'
    +'（对数） · 悬浮看单条明细</div>';
}
function drawTable(s){
  var el=$('#reqView');if(!el)return;
  /* 总量口径下单个会话请求可达上千条：表格只渲染最近 500 条，避免 DOM 过大拖慢页面 */
  var CAP=500,all=s.rs.slice().reverse(),show=all.slice(0,CAP);
  var rows=show.map(function(r){var d=new Date(r[0]*60000);
    var tipTxt='输入 '+nf(r[3])+' · 输出 '+nf(r[4])+' · 缓存 '+nf(r[5])+' · 合计 '+nf(r[2]);
    return '<tr data-tip="'+esc(tipTxt)+'"><td class="mono">'+fd(d)+' '+ft(d)+'</td>'
      +'<td style="text-align:left">'+esc(models[r[1]])+'</td><td class="mono">'+nf(r[3])
      +'</td><td class="mono">'+nf(r[4])+'</td><td class="mono">'+nf(r[5])
      +'</td><td class="mono">'+nf(r[2])+'</td></tr>';}).join('');
  var note=all.length>CAP?('<div style="margin-bottom:6px;font-size:10px;color:var(--t3)">'
    +'共 '+nf(all.length)+' 次请求 · 表格显示最近 '+CAP+' 次（更早请求见散点图）</div>'):'';
  el.innerHTML=note+'<div class="rt-wrap"><table><thead><tr><th>时间</th>'
    +'<th style="text-align:left">模型</th><th>输入</th><th>输出</th><th>缓存命中</th>'
    +'<th>合计</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
}


/* ---------------- 名字列测宽：模型名 + 厂商 chip 一并完整显示 ---------------- */
/* .nm 虽然 overflow:hidden，scrollWidth 仍能读出完整内容宽度；取全行最大值写入
   CSS 变量 --nmw（.mrow 第一列走 var(--nmw,200px)），条形/数值列随之给足空间。
   上限 minmax 之外的 cap：最多吃 42% 视窗宽，防止个别超长名挤没条形。 */
function fitModelNameCol(){
  var w=200;
  [].forEach.call(document.querySelectorAll('#modelRows .nm'),function(el){
    var sw=el.scrollWidth+2;if(sw>w)w=sw;});
  w=Math.min(w,Math.max(200,window.innerWidth*0.42));
  document.documentElement.style.setProperty('--nmw',Math.round(w)+'px');
}

/* ---------------- 总调度 ---------------- */
function renderAll(){
  var A=aggregate();LASTA=A;
  renderHero(A);renderKpis(A);
  $('#modelRows').innerHTML=modelRows(A);
  fitModelNameCol();
  $('#modelCap').innerHTML='同厂商模型用明度阶梯区分，色相保持品牌体系 · 全局 50% 单次请求 '
    +fmt(A.gp50);
  renderDaily(A);renderModelTotals(A);  renderHour(A);renderDist(A);renderHeat(A);
  renderPanel(A);
  [].forEach.call(document.querySelectorAll('.ppill'),function(b){
    var w=+b.dataset.w;
    /* 指定日 / 总量模式期间不点亮常规周期预设；自定义窗口高亮它自己的 data-w=-1 标签 */
    b.classList.toggle('on',!dayMode&&(
      (w>0&&win===w)||(w===-1&&win===0)||(w===-2&&allMode)));});
  var pick=$('#dayPick');if(pick)pick.classList.toggle('on',dayMode);
}
window.addEventListener('resize',fitModelNameCol);

/* ---------------- 事件 ---------------- */
document.addEventListener('click',function(ev){
  var t=ev.target;if(!t||!t.closest)return;
  if(t.closest('#dayPick'))return;   // 单日控件有自己的监听器，不走全局委托
  var n;
  if((n=t.closest('[data-a]'))){
    if(n.dataset.a==='root'){state={ws:null,ses:null};renderAll();}
    else if(n.dataset.a==='up'&&state.ws!==null){state={ws:state.ws,ses:null};renderAll();}
    return;}
  if((n=t.closest('[data-ws]'))){state={ws:+n.dataset.ws,ses:null};renderAll();return;}
  if((n=t.closest('[data-si]'))){
    var idx=+n.dataset.si,entry=null;
    if(LASTA)for(var i=0;i<LASTA.sessT.length;i++){
      if(LASTA.sessT[i].i===idx){entry=LASTA.sessT[i];break;}}
    if(entry){state={ws:entry.s.w,ses:idx};renderAll();}
    return;}
  if((n=t.closest('.ppill'))){var wv=+n.dataset.w;
    if(wv===0){enterDayMode();return;}   // 「指定日」开关，不是周期天数
    if(wv===-2){allMode=true;win=0;cLo=0;cHi=0;exitDayMode();selModel=null;
      $('#dStart').value='';$('#dEnd').value='';renderAll();return;}
    if(wv<0)return;
    allMode=false;exitDayMode();
    win=wv;cLo=0;cHi=0;selModel=null;
    $('#dStart').value='';$('#dEnd').value='';renderAll();return;}
  if((n=t.closest('[data-m]'))){wsMode=n.dataset.m;
    [].forEach.call(document.querySelectorAll('#wsTools [data-m]'),function(b){
      b.classList.toggle('on',b===n);});renderAll();return;}
  if((n=t.closest('[data-s]'))){wsSort=n.dataset.s;
    [].forEach.call(document.querySelectorAll('#wsTools [data-s]'),function(b){
      b.classList.toggle('on',b===n);});renderAll();return;}
  if((n=t.closest('[data-dm]'))){var mi=+n.dataset.dm;
    selModel=(selModel===mi?null:mi);renderAll();return;}
  if((n=t.closest('[data-hv]'))){heatView=n.dataset.hv;
    if(LASTA)renderHeat(LASTA);return;}
  if((n=t.closest('[data-span]'))){dailySpan=n.dataset.span;
    [].forEach.call(document.querySelectorAll('#dailySpan [data-span]'),function(b){
      b.classList.toggle('on',b===n);});
    if(LASTA)renderDaily(LASTA);return;}
});
$('#wsSearch').addEventListener('input',function(ev){
  q=ev.target.value.trim().toLowerCase();renderAll();});
$('#wsGran').addEventListener('change',function(ev){wsGran=ev.target.value;renderAll();});
var hourTopSel=$('#hourTop');
if(hourTopSel)hourTopSel.addEventListener('change',function(ev){
  hourTop=+ev.target.value;if(LASTA)renderHour(LASTA);});
var hourModeSel=$('#hourMode');
if(hourModeSel)hourModeSel.addEventListener('change',function(ev){
  hourMode=ev.target.value;if(LASTA)renderHour(LASTA);});
var distTopSel=$('#distTop');
if(distTopSel)distTopSel.addEventListener('change',function(ev){
  distTop=+ev.target.value;if(LASTA)renderDist(LASTA);});
var wsTopSel=$('#wsTop');
if(wsTopSel)wsTopSel.addEventListener('change',function(ev){
  wsTop=+ev.target.value;if(LASTA)renderPanel(LASTA);});
$('#platSel').addEventListener('change',function(ev){
  platFilter=ev.target.value===''?-1:+ev.target.value;
  selModel=null;state={ws:null,ses:null};renderAll();});
function applyCustom(){
  var sv=$('#dStart').value,ev=$('#dEnd').value;if(!sv&&!ev)return;
  exitDayMode();allMode=false;
  cLo=sv?Math.floor(new Date(sv+'T00:00:00').getTime()/60000):0;
  cHi=ev?Math.floor((new Date(ev+'T00:00:00').getTime()+86400e3)/60000):0;
  win=0;selModel=null;renderAll();}
$('#dStart').addEventListener('change',applyCustom);
$('#dEnd').addEventListener('change',applyCustom);

/* ---------------- 指定日模式 ---------------- */
function exitDayMode(){dayMode=false;var t=$('#dayPickTxt');if(t)t.textContent='指定日';}
function enterDayMode(key){
  var sel=$('#daySel');
  var v=key||(sel&&sel.value)||focusDayKey();
  /* 夹到数据真实覆盖范围内，避免选到必定空白的日期 */
  if(sel&&sel.min&&v<sel.min)v=sel.min;
  if(sel&&sel.max&&v>sel.max)v=sel.max;
  if(!v)return;
  dayKey=v;dayMode=true;allMode=false;
  if(sel)sel.value=v;
  var t=$('#dayPickTxt');if(t)t.textContent=v;   // pill 直接显示所选日期
  $('#dStart').value='';$('#dEnd').value='';
  selModel=null;state={ws:null,ses:null};
  renderAll();
}
var daySel=$('#daySel');
if(daySel)daySel.addEventListener('change',function(ev){
  if(ev.target.value)enterDayMode(ev.target.value);});
var themeBtn=document.getElementById('themeBtn');
themeBtn.textContent=DARK?'浅色':'深色';
themeBtn.onclick=function(){DARK=!DARK;HEAT=DARK?HEAT_D:HEAT_L;
  document.body.dataset.theme=DARK?'dark':'light';
  try{localStorage.setItem('tb-theme',DARK?'dark':'light');}catch(e){}
  themeBtn.textContent=DARK?'浅色':'深色';renderAll();};
/* 刷新：在 tokenboard serve 模式下会重新扫描本机日志拉取最新数据；
   直接双击打开静态文件时则仅重载当前嵌入的快照。 */
var refreshBtn=document.getElementById('refreshBtn');
if(refreshBtn)refreshBtn.onclick=function(){
  var t0=Date.now(),old=refreshBtn.textContent;
  refreshBtn.disabled=true;refreshBtn.textContent='刷新中…';
  // 让「刷新中」先绘制出来，再 reload
  setTimeout(function(){location.reload();},30);
  setTimeout(function(){refreshBtn.disabled=false;refreshBtn.textContent=old;},2000);
};
/* ---------------- 数据源表：单平台导入 ----------------
   列的初始状态完全由服务端按「本机真实日志」渲染，前端不做会话状态重放（单一数据源）。
   只有 serve 实时模式（http/https）能真正回读本机日志；静态 file:// 仅给降级提示。
   点导入 = 服务端真扫一遍并检测本机安装状态：
     · 真正扫到数据 → 已导入 / 已验证 / 重新导入，延迟 reload 让数据并入看板；
     · 本机未安装或 0 条 → 保持 未导入 / 未验证 / 导入按钮，明确提示，绝不假装成功。 */
var IS_SERVE=(location.protocol==='http:'||location.protocol==='https:');
var impBusy=false;
function impRow(plat){
  var b=document.querySelector('.impbtn[data-plat="'+plat+'"]');
  return b?b.closest('tr'):null;
}
/* 仅在服务端确实扫到记录时调用 */
function paintImported(plat,rec){
  var tr=impRow(plat);if(!tr)return;
  var cell=tr.querySelector('[data-role="import"]');
  var v=tr.querySelector('[data-role="verify"]');
  if(v){v.className='pill ok';v.textContent='已验证';}
  var s=cell&&cell.querySelector('[data-role="impst"]');
  if(s){s.className='impst ok';s.textContent='✓ 已导入'+(rec!=null?' · '+rec+' 条':'');}
  var btn=cell&&cell.querySelector('.impbtn');
  if(btn){btn.classList.add('ghost');btn.textContent='重新导入';btn.disabled=false;}
}
function doImport(plat){
  if(impBusy)return;
  var tr=impRow(plat);if(!tr)return;
  var cell=tr.querySelector('[data-role="import"]');
  var btn=cell&&cell.querySelector('.impbtn');
  var st=cell&&cell.querySelector('[data-role="impst"]');
  if(!IS_SERVE){
    /* 本机有数据的行本来就是「已导入」，快照模式下点「重新导入」不应覆盖成警告；
       只有还处于「未导入」的行才需要提示改用实时模式。 */
    if(st&&st.classList.contains('yet')){
      st.className='impst warn';st.textContent='需用 serve.command 实时模式';
    }
    if(btn)btn.title='双击打开的静态文件无法扫描本机日志；请用 ./serve.command（本地服务版）打开后再导入';
    return;
  }
  impBusy=true;
  if(btn){btn.disabled=true;btn.textContent='检测中…';}
  fetch('/api/import?platform='+encodeURIComponent(plat),{cache:'no-store'})
    .then(function(r){return r.json();})
    .then(function(j){
      if(!j.ok)throw new Error(j.error||'导入失败');
      var fc=tr.querySelector('[data-role="files"]');
      if(fc&&j.file_count!=null)fc.textContent=j.file_count;
      if(j.imported){
        paintImported(plat,j.record_count);
        setTimeout(function(){location.reload();},700);
      }else{
        /* 本机未安装 / 暂无日志：状态列保持未验证，按钮仍是「导入」，不 reload */
        var v=tr.querySelector('[data-role="verify"]');
        if(v){v.className='pill no';v.textContent='未验证';}
        if(st){st.className='impst warn';st.textContent=j.message||'本机未安装或暂无日志';}
        if(btn){btn.disabled=false;btn.textContent='导入';btn.classList.remove('ghost');
                btn.title='未检测到该平台数据；确认本机已安装并产生日志后可再次导入';}
      }
    })
    .catch(function(err){
      if(st){st.className='impst warn';st.textContent='导入失败：'+(err.message||'');}
      if(btn){btn.disabled=false;btn.textContent='重试';}
    })
    .then(function(){impBusy=false;});
}
document.addEventListener('click',function(ev){
  var b=ev.target&&ev.target.closest?ev.target.closest('.impbtn'):null;
  if(b&&b.dataset.plat)doImport(b.dataset.plat);
});
renderAll();
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
    if value <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(value))
    for factor in (1, 2, 2.5, 5, 10):
        if value <= factor * mag:
            return factor * mag
    return 10 * mag


def _smooth_path(points: list[tuple[float, float]]) -> str:
    """Catmull-Rom → 三次贝塞尔（Python 静态首屏用；JS 端用 Fritsch-Carlson）。"""
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
    raw1, raw2 = hex_color.lstrip("#"), other.lstrip("#")
    out = []
    for i in (0, 2, 4):
        a, b = int(raw1[i:i + 2], 16), int(raw2[i:i + 2], 16)
        out.append(round(a + (b - a) * t))
    return "#" + "".join(f"{max(0, min(255, v)):02X}" for v in out)


def _vars(tokens: dict[str, str]) -> str:
    mapping = {
        "bg": "--bg", "surface": "--surface", "surface_2": "--surface2",
        "border": "--bd", "border_strong": "--bds", "text_1": "--t1",
        "text_2": "--t2", "text_3": "--t3", "brand": "--brand",
        "brand_bright": "--brandb", "brand_soft": "--brandsoft",
        "on_brand": "--onbrand", "success": "--ok", "warning": "--warn",
        "danger": "--danger",
    }
    return "".join(f"{css}:{tokens[key]};" for key, css in mapping.items() if key in tokens)


def _heat_css(name: str) -> str:
    return "".join(f"--h{i}:{c};" for i, c in enumerate(HEATMAPS.get(name, HEATMAPS["light"])))


def _heat_json(name: str) -> str:
    return json.dumps(list(HEATMAPS.get(name, HEATMAPS["light"])))


def _ws_order(summary: Summary) -> list[str]:
    """工作空间唯一排序（Token 降序、名称升序）；静态首屏与 JS 载荷共用同一顺序，
    保证 data-ws 下标在两边指向同一个工作空间。"""
    return sorted(
        summary.by_workspace,
        key=lambda w: (-summary.by_workspace[w]["tokens"], w),
    )


# ------------------------------------------------------------------ 数据载荷

def _payload(
    summary: Summary,
    records: Sequence[UsageRecord],
    palette: dict[str, str],
    prices: dict | None,
    generated: str,
    window_days_: int | None,
    custom_range: tuple[int | None, int | None] | None,
) -> dict[str, Any]:
    """把请求级明细压成页面内可聚合的最小载荷（分钟粒度）。"""
    models = summary.models
    model_idx = {m: i for i, m in enumerate(models)}
    ws_names = _ws_order(summary)
    ws_idx = {w: i for i, w in enumerate(ws_names)}
    platforms = sorted(summary.by_platform)
    plat_idx = {p: i for i, p in enumerate(platforms)}

    sess_map: dict[tuple[str, str], list[UsageRecord]] = {}
    for rec in records:
        sess_map.setdefault((rec.platform, rec.session_id), []).append(rec)
    sessions = []
    for (platform, sid), rs in sess_map.items():
        rs = sorted(rs, key=lambda r: r.ts)
        recs = [
            [r.ts // 60, model_idx.get(r.model, 0), r.total_tokens, r.input_tokens,
             r.output_tokens, r.cache_read_tokens, r.cache_write_tokens]
            for r in rs
        ]
        title = (rs[0].title or "").strip() or sid
        if len(title) > 44:
            title = title[:24] + "…" + title[-14:]
        sessions.append({
            "w": ws_idx.get(rs[0].workspace, 0),
            "p": plat_idx.get(platform, 0),
            "t": title,
            "r": recs,
        })
    sessions.sort(key=lambda s: -sum(x[2] for x in s["r"]))
    price_table = []
    for m in models:
        p = price_of(m, prices)
        price_table.append([p.input, p.output, p.cache_read])
    last_ts = summary.last_ts or int(datetime.now().timestamp())
    # 生成当日结束（次日 00:00，本地时区）作为周期窗口与日活热力的锚点。
    # 从 generated 字符串解析，保证与页眉「数据截至」展示的是同一天；
    # 旧口径 genMin 锚定最后一条日志，日志停在几天前时「近 N 天」不会跟到当天。
    try:
        gen_dt = datetime.strptime(generated, "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        gen_dt = datetime.now()
    day_end = datetime(gen_dt.year, gen_dt.month, gen_dt.day) + timedelta(days=1)
    day_anchor = int(day_end.timestamp()) // 60
    custom = None
    if custom_range and (custom_range[0] or custom_range[1]):
        lo = custom_range[0] // 60 if custom_range[0] else 0
        hi = custom_range[1] // 60 if custom_range[1] else 0
        custom = [lo, hi]
    return {
        "gen": generated,
        "genMin": last_ts // 60,
        "dayAnchor": day_anchor,
        "win": window_days_ if window_days_ is not None else (None if custom else DEFAULT_VIEW_DAYS),
        "custom": custom,
        "models": models,
        "palette": [palette[m] for m in models],
        "vendor": [vendor_of(m) for m in models],
        "prices": price_table,
        "platforms": platforms,
        "workspaces": ws_names,
        "sessions": sessions,
    }


# ------------------------------------------------------------------ 静态首屏

def _hero(summary: Summary, window_note: str) -> str:
    kpi = summary.kpi()
    top_model = summary.models[0] if summary.models else "—"
    top_share = (
        summary.by_model[top_model]["tokens"] / summary.total_tokens * 100
        if summary.total_tokens and summary.models else 0.0
    )
    warn = f'<div class="warn" id="heroWarn">{e(window_note)}</div>' if window_note \
        else '<div class="warn" id="heroWarn"></div>'
    return (
        '<div class="hero"><div class="lab">本 期 结 论</div>'
        f'<div class="main" id="heroMain">{fmt(summary.total_tokens)} Token&ensp;·&ensp;'
        f'{kpi["requests"]:,} 次请求&ensp;·&ensp;预估 ¥{kpi["estimated_cost_cny"]:.2f}</div>'
        f'<div class="sub2" id="heroSub">缓存命中 {kpi["cache_hit_rate"]:.1f}%&ensp;·&ensp;'
        f'主力模型 {e(top_model)} 占 {top_share:.1f}%&ensp;·&ensp;'
        f'覆盖 {len(summary.by_platform)} 个平台 / {kpi["active_days"]} 个有数据日</div>{warn}'
        f'<div class="side"><div class="k">折合单价</div>'
        f'<div class="v" id="heroPrice">¥{kpi["price_per_million_cny"]:.2f} / 百万</div></div></div>'
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
    if not summary.models:
        return '<div class="cap">暂无数据</div>'
    cap = max(summary.by_model[m]["tokens"] for m in summary.models[:8]) or 1
    rows = []
    for mi, m in enumerate(summary.models[:8]):
        tokens = summary.by_model[m]["tokens"]
        share = tokens / summary.total_tokens * 100 if summary.total_tokens else 0
        rows.append(
            f'<div class="mrow"><span class="nm" data-dm="{mi}" title="点击聚焦该模型">'
            f'<i class="dot" style="background:{e(palette[m])}"></i>{e(m)}'
            f'<span class="vendor">{e(vendor_of(m))}</span></span>'
            f'<span class="track"><i style="width:{tokens / cap * 100:.1f}%;'
            f'background:{e(palette[m])}"></i></span>'
            f'<span class="num">{fmt(tokens)}&ensp;·&ensp;{e(vendor_of(m))}&ensp;·&ensp;'
            f'{share:.1f}%</span></div>'
        )
    # 缓存命中率 / 输入·输出比已在 KPI 区呈现，这里不再重复画低区分度的进度条
    return "".join(rows)


def _daily_card(records: Iterable[UsageRecord], summary: Summary, palette: dict[str, str]) -> str:
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
                f'fill="{e(palette[model])}" fill-opacity="0.92" '
                f'stroke="var(--bg)" stroke-width=".6"><title>{e(day)} · {e(model)} · {fmt(value)}</title></rect>'
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
        f'<span data-dm="{mi}"><i style="background:{e(palette[m])}"></i>{e(m)}</span>'
        for mi, m in enumerate(summary.models[:6])
    )
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def _model_totals_card(summary: Summary, palette: dict[str, str]) -> str:
    if not summary.models:
        return '<h3>单模型总量统计</h3><div class="cap">暂无数据</div>'
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
        '<h3>单模型总量统计</h3>'
        '<div class="seg" id="metricSeg" role="group" aria-label="显示口径切换">'
        '<button type="button" class="on" data-metric-opt="token">按 Token</button>'
        '<button type="button" data-metric-opt="cost">按金额</button></div>'
        '<span class="hdnote" style="margin-left:auto">周期跟随全局时间窗口</span></div>'
        f'<div class="cap">{e(caption)}</div>' + table
    )


def _hourly_card(summary: Summary, palette: dict[str, str],
                 top_n: int = DEFAULT_HOUR_TOP) -> str:
    # top_n=0 表示全部模型；summary.models 已按 Token 降序，与 JS 的 orderByTokens 同序
    top = summary.models[:top_n] if top_n > 0 else summary.models
    if not top or not any(summary.hourly):
        return '<div class="cap">暂无数据</div>'
    width, base = 1240, 150
    peak = _nice_max(max(max(summary.hourly_by_model.get(m, [0] * 24)) for m in top))
    step = width / 24.0

    def curve(model: str) -> tuple[str, str]:
        series = summary.hourly_by_model.get(model, [0] * 24)
        pts = [(h * step, base - v / peak * (base - 12)) for h, v in enumerate(series)]
        line = _smooth_path(pts)
        return line, f"{line} L{width},{base} L0,{base} Z"

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
        parts.append(f'<path d="{area}" fill="{e(palette[m])}" '
                     f'fill-opacity="{0.16 if i == 0 else 0.12}" stroke="none"/>')
        parts.append(f'<path d="{line}" fill="none" stroke="{e(palette[m])}" stroke-width="2"/>')
    for hour in range(0, 24, 2):
        parts.append(f'<text x="{hour * step + 6:.1f}" y="{base + 22}" fill="var(--t3)" '
                     f'font-size="10">{hour}时</text>')
    parts.append("</svg>")
    legend = "".join(
        f'<span data-dm="{mi}"><i style="background:{e(palette[m])}"></i>{e(m)} · {e(vendor_of(m))}</span>'
        for mi, m in enumerate(top)
    )
    return f'<div class="legend" style="justify-content:flex-end">{legend}</div>' \
           + f'<div class="hchart">{"".join(parts)}</div>'


def _request_size_card(summary: Summary, palette: dict[str, str]) -> str:
    # 与页面 #distTop 下拉的默认值保持一致（默认 TOP 3）
    dist = summary.distribution(top=DEFAULT_DIST_TOP)
    models_ = [d for d in dist["models"] if d["count"]]
    if not models_:
        return '<div class="cap">暂无数据</div>'
    cap = max(d["p90"] for d in models_) or 1
    head = ('<div class="dhead drow" style="border-bottom:1px solid var(--bd)"><span>模型</span>'
            '<span>次数</span><span>50%</span><span>90%</span></div>')
    rows = []
    for d in models_:
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
    width, base = 860, 150
    hi = _nice_max(cap * 1.35)
    bins = 36
    hists: dict[str, list[float]] = {}
    for d in models_:
        sizes = summary.model_sizes.get(d["name"], [])
        hist = [0] * bins
        for v in sizes:
            hist[min(bins - 1, int(v / hi * bins))] += 1
        peak = max(hist) or 1
        hists[d["name"]] = [h / peak for h in hist]
    step = width / bins
    parts = [f'<svg viewBox="0 0 {width} {base + 26}" role="img" aria-label="单次请求大小分布">']
    parts.append(f'<line x1="0" y1="{base}" x2="{width}" y2="{base}" '
                 'stroke="var(--bds)" stroke-width="1"/>')
    for d in models_:
        color = palette.get(d["name"], "#5FC2A0")
        pts = [(i * step + step / 2, base - v * (base - 16))
               for i, v in enumerate(hists[d["name"]])]
        line = _smooth_path(pts)
        parts.append(f'<path d="{line} L{width},{base} L0,{base} Z" '
                     f'fill="{e(color)}" fill-opacity="0.14"/>')
        parts.append(f'<path d="{line}" fill="none" stroke="{e(color)}" stroke-width="2"/>')
        parts.append(f'<line x1="{d["p50"] / hi * width:.1f}" y1="26" '
                     f'x2="{d["p50"] / hi * width:.1f}" y2="{base}" '
                     f'stroke="{e(color)}" stroke-width="1.5" stroke-opacity=".8"/>')

        def curve_y(hist: Sequence[float], value: float) -> float:
            pos = min(len(hist) - 1.0, max(0.0, value / hi * len(hist)))
            low = int(pos)
            high = min(len(hist) - 1, low + 1)
            frac = pos - low
            return hist[low] * (1 - frac) + hist[high] * frac

        y90 = base - curve_y(hists[d["name"]], d["p90"]) * (base - 16)
        cx90 = d["p90"] / hi * width
        # p90 点跟随模型色 + 白描边；透明大圆扩大命中区，悬停给出专属说明
        p90_tip = e(f'{d["name"]}\n90% 的请求单次 ≤ {fmt(d["p90"])} token\n'
                    f'共 {d["count"]:,} 次 · 50% {fmt(d["p50"])} token')
        parts.append(f'<circle cx="{cx90:.1f}" cy="{y90:.1f}" r="4" '
                     f'fill="{e(color)}" stroke="#fff" stroke-width="1.5"/>')
        parts.append(f'<circle cx="{cx90:.1f}" cy="{y90:.1f}" r="11" fill="transparent" '
                     f'pointer-events="all" data-tip="{p90_tip}"/>')
    gx = dist["global_p50"] / hi * width
    parts.append(f'<line x1="{gx:.1f}" y1="14" x2="{gx:.1f}" y2="{base}" '
                 'stroke="var(--t3)" stroke-width="1" stroke-dasharray="4 4"/>')
    parts.append(f'<text x="{min(width - 4, gx + 6):.1f}" y="24" fill="var(--t3)" font-size="10">'
                 f'全局 50% {fmt(dist["global_p50"])}</text>')
    for frac in (0, 1 / 3, 2 / 3, 1):
        anchor = ' text-anchor="end"' if frac == 1 else ""
        parts.append(f'<text x="{width * frac:.1f}" y="{base + 20}" fill="var(--t3)" '
                     f'font-size="10"{anchor}>{"0" if frac == 0 else fmt(hi * frac)}</text>')
    parts.append("</svg>")
    caption = ("每模型一条分布形状（各自归一）· 实线=该模型 50% · "
               "同色圆点=该模型 90%（悬浮看数值）· 虚线=全局 50% · "
               "数值下条形=两列共享刻度的大小对比（深=50% 浅=90%）")
    return (
        f'<div class="distwrap"><div>{left}</div><div>{"".join(parts)}'
        f'<div class="cap" style="margin-top:8px">{e(caption)}</div></div></div>'
    )


def _dayhour_card(summary: Summary, heat_anchor: str | None) -> str:
    if not summary.hour_matrix:
        return '<div class="cap">暂无数据</div>'
    band_total = sum(summary.bands) or 1
    band_names = ("凌晨 0—6", "上午 6—12", "下午 12—18", "晚间 18—24")
    chips = "".join(
        f'<div class="chip2"><span>{e(n)}</span><b>{v / band_total * 100:.1f}%</b></div>'
        for n, v in zip(band_names, summary.bands)
    )
    data_days = sorted(summary.hour_matrix)
    last_data = datetime.strptime(data_days[-1], "%Y-%m-%d")
    # 与 JS 日视图同构：常规窗口锚定「生成当日」向前 7 个自然日（含空窗日，诚实显示）；
    # 自定义历史窗口时 heat_anchor 为 None，锚定窗口内最后有数据日，避免视图落在窗口外。
    if heat_anchor:
        try:
            gen_day = datetime.strptime(heat_anchor, "%Y-%m-%d")
        except (ValueError, TypeError):
            gen_day = last_data
        anchor = max(gen_day, last_data)
    else:
        anchor = last_data
    days = [(anchor - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    peak = max((v for d in days for v in summary.hour_matrix.get(d, (0,) * 24)), default=0) or 1
    # 日期文字与热力格放进同一张 SVG（整体缩放后天然对齐），小时刻度精确落在
    # 每列中心。旧版把日期做成固定高度的 HTML 标签列，而 SVG 自适应宽度整体
    # 缩放，两套行距缩放比例不同，行数一多日期就漂移错位。
    cell, gap, label_w, top = 40, 6, 80, 22
    row_h, row_gap = 16, 8
    width = label_w + 24 * (cell + gap)
    height = top + len(days) * (row_h + row_gap) + 2
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="日 × 小时热力图">']
    for hour in range(24):
        cx = label_w + hour * (cell + gap) + cell / 2
        parts.append(
            f'<text x="{cx:.1f}" y="12" fill="var(--t3)" font-size="9" '
            f'text-anchor="middle">{hour}</text>'
        )
    for r, day in enumerate(days):
        y = top + r * (row_h + row_gap)
        dim = "var(--t3)" if day not in summary.hour_matrix else "var(--t2)"
        parts.append(
            f'<text x="{label_w - 8}" y="{y + row_h / 2 + 3.5:.1f}" fill="{dim}" '
            'font-size="10" text-anchor="end" style="font-family:var(--mono)">'
            f'{e(day[5:7])}—{e(day[8:10])}</text>'
        )
        row = summary.hour_matrix.get(day, (0,) * 24)
        for hour in range(24):
            v = row[hour]
            level = 0 if v <= 0 else min(6, 1 + int(v / peak * 5.999))
            x = label_w + hour * (cell + gap)
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{row_h}" rx="3" '
                f'fill="var(--h{level})"><title>{e(day)} {hour}:00 · {fmt(v)}</title></rect>'
            )
    parts.append("</svg>")
    swatches = "".join(f'<i style="background:var(--h{i})"></i>' for i in range(7))
    legend = f'<div class="hmlegend">低 {swatches} 高</div>'
    return f'<div class="chips">{chips}</div>{legend}{"".join(parts)}'


def _sources_card(statuses: Sequence[SourceStatus], imported: Sequence[str] = ()) -> str:
    """数据源状态表；imported 为本次 serve 会话中「真正导入了数据」的平台内部 key。

    列的语义只认**本机真实状态**，不采用适配器开发期的 ``verified`` 静态标记：
      * 本机发现该平台日志文件（``file_count > 0``），或本次会话已确实扫出记录
        → 「✓ 已导入 / 已验证 / 重新导入」；
      * 本机未安装、没有日志（``file_count == 0`` 且未导入）
        → 「未导入 / 未验证 / 导入」。
    这样本机没装的平台不会误显示「已导入」。serve 端只在 ``record_count > 0``
    时才把平台写进 imported，因此集合里不会混入 0 数据的平台。
    底层 SourceStatus / 适配器类属性不受影响，CLI / MCP / JSON 等出口仍是原语义。
    """
    imported_set = set(imported)
    rows = []
    for s in statuses:
        is_imp = (s.file_count > 0) or (s.name in imported_set)
        pill = ('<span class="pill ok" data-role="verify">已验证</span>' if is_imp
                else '<span class="pill no" data-role="verify">未验证</span>')
        note = e(s.note) if s.note else "本机未安装或没有日志可供核对"
        root = e(s.roots[0]) if s.roots else "—"
        # 状态 class 直接落在 data-role="impst" 这个 span 上（不嵌套），
        # 前端才能用 classList.contains('yet') 判断是否还处于未导入。
        if is_imp:
            imp_cls, imp_text = "impst ok", "✓ 已导入"
            btn_label, btn_cls = "重新导入", "impbtn ghost"
        else:
            imp_cls, imp_text = "impst yet", "未导入"
            btn_label, btn_cls = "导入", "impbtn"
        imp_cell = (
            '<td class="impcell" data-role="import">'
            f'<button type="button" class="{btn_cls}" data-plat="{e(s.name)}" '
            'title="检测本机是否安装该平台并扫描日志；仅真正导入数据后才显示已导入">'
            f'{btn_label}</button>'
            f'<span class="{imp_cls}" data-role="impst">{imp_text}</span></td>'
        )
        rows.append(
            f'<tr><td style="color:var(--t1);font-weight:600">{e(s.display_name)}</td>'
            f'<td class="mono">{root}</td>'
            f'<td class="mono" data-role="files">{s.file_count}</td>'
            f'<td>{pill}</td>{imp_cell}'
            f'<td style="font-size:10.5px">{note}</td></tr>'
        )
    live = ('<span class="livedot"></span><span style="font-size:10px;color:var(--t2)">'
            "本机日志已连接</span>") if any(
                (s.file_count > 0) or (s.name in imported_set) for s in statuses) else ""
    table = (
        "<table><thead><tr><th>平台</th><th>默认路径</th><th>文件</th><th>状态</th>"
        '<th title="扫描并接入该平台数据源；仅 serve 实时模式可真正回读本机日志">导入状态</th>'
        "<th>说明</th></tr></thead><tbody>"
        + ("".join(rows) or '<tr><td colspan="6">未指定数据源</td></tr>')
        + "</tbody></table>"
    )
    return f'<div style="position:absolute;right:22px;top:16px">{live}</div>' + table


def _workspace_card(summary: Summary) -> str:
    """静态首屏的工作空间行（JS 加载后会按当前窗口重绘并接管点击）。"""
    if not summary.by_workspace:
        return '<div class="cap">暂无数据</div>'
    total = summary.total_tokens or 1
    full = _ws_order(summary)
    # 与 JS 默认粒度一致（#wsGran 默认「日 · 24 时」）：首屏 24 格占位，JS 加载后
    # 按当前窗口与粒度重绘接管；平台列取该工作空间涉及的全部平台。
    head = ('<div class="wshead"><span>工作空间</span><span>平台</span><span>Token</span>'
            '<span>占比 / 会话</span><span>分布（日 · 24 时）</span><span></span></div>')
    rows = []
    for idx, w in enumerate(full[:DEFAULT_WS_TOP]):
        info = summary.by_workspace[w]
        sessions = summary.ws_sessions.get(w, ())
        chips = "".join(f'<span class="pchip">{e(p)}</span>' for p in sorted({p for p, _ in sessions}))
        segs = '<i style="flex:1;background:var(--brand);opacity:.85"></i>' * 24
        name = e(w)
        rows.append(
            f'<div class="wsrow click" data-ws="{idx}">'
            f'<span class="nm" title="{name}">{name}</span>'
            f'<span class="wplat">{chips}</span>'
            f'<span class="tk">{fmt(info["tokens"])}</span>'
            f'<span class="sh">{info["tokens"] / total * 100:.1f}%'
            f'<small>· {len(sessions)} 会话</small></span>'
            f'<span class="wviz">{segs}</span><span class="chev">›</span></div>'
        )
    return head + "".join(rows)


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
    window_label: str = DEFAULT_VIEW_LABEL,
    window_days: int | None = DEFAULT_VIEW_DAYS,
    custom_range: tuple[int | None, int | None] | None = None,
    prices: dict | None = None,
    imported: Sequence[str] = (),
) -> str:
    """渲染完整的单文件 HTML；不访问网络、不写文件。

    ``window_days`` / ``custom_range`` / ``prices`` 会随请求级明细一起嵌入页面，
    供 JS 端在浏览器内重新聚合（周期切换 / 下钻）。
    """
    generated = generated or datetime.now().strftime("%Y-%m-%d %H:%M")
    kpi = summary.kpi()
    palette = palette_for(summary.models)

    hero = _hero(summary, window_note)
    kpis = _kpi_cards([
        ("合计 Token", fmt(summary.total_tokens), "", True),
        ("请求轮次", f'{kpi["requests"]:,}', "", False),
        ("缓存命中率", f'{kpi["cache_hit_rate"]:.1f}', "%", False),
        ("预估金额（元）", f'¥{kpi["estimated_cost_cny"]:.2f}', "", False),
        ("日均（有数据天）", fmt(summary.daily_average), "", False),
        ("会话", f'{kpi["sessions"]:,}', "", False),
        ("输入 / 输出比", f'{kpi["input_output_ratio"]:.1f} : 1', "", False),
    ])

    periods = []
    known = {"1 天": 1, "2 天": 2, "3 天": 3, "近 7 天": 7, "近 30 天": 30}
    # CLI / serve 生成的 window_label 可能是「近 2 天」「近 3 天」这类别名，
    # 统一按天数折算回预设标签，避免同一窗口既点亮预设又多出一颗重复标签。
    active_label = next(
        (lbl for lbl, wv in known.items() if wv == window_days), window_label
    )
    for lbl, wv in known.items():
        on = ' class="ppill on"' if lbl == active_label else ' class="ppill"'
        periods.append(f'<button{on} data-w="{wv}">{lbl}</button>')
    # 「总量」= 跨全部日期的累计消耗（不受近 N 天窗口限制）；data-w=-2 为全量模式哨兵。
    periods.append('<button class="ppill" data-w="-2" title="显示全部日期的全部 Token 消耗">总量</button>')
    if active_label not in known:
        periods.append(f'<button class="ppill on" data-w="-1">{e(window_label)}</button>')
    # 「指定日」不再作为预设按钮塞进周期组，而是单独成一颗日期 pill（见模板 #dayPick），
    # 点击即弹出原生日历，选定后整颗 pill 显示该日期并高亮。
    period_pills = "".join(periods)

    # 单日日历的可选范围 = 嵌入页面的记录真实覆盖日期（records 已按 --since 过滤）。
    # 初值取「生成当日」与「数据末日」的较小者，避免默认落到一个必定空白的日期。
    if records:
        day_min = datetime.fromtimestamp(min(r.ts for r in records)).strftime("%Y-%m-%d")
        day_max = datetime.fromtimestamp(max(r.ts for r in records)).strftime("%Y-%m-%d")
        day_val = min(generated[:10], day_max)
        if day_val < day_min:
            day_val = day_min
    else:
        day_min = day_max = ""
        day_val = generated[:10]

    display_names = {getattr(s, "name", ""): getattr(s, "display_name", "") for s in statuses}
    plat_opts = '<option value="">全部平台</option>' + "".join(
        f'<option value="{i}">{e(display_names.get(p, p) or p)}</option>'
        for i, p in enumerate(sorted(summary.by_platform))
    )

    ws_opts = "".join(
        f'<option value="{value}"'
        f'{" selected" if value == DEFAULT_WS_TOP else ""}>{label}</option>'
        for value, label in ((5, "TOP 5"), (10, "TOP 10"), (0, "全部工作空间"))
    )
    # 0—24 时分布·按模型：曲线数量下拉（默认 TOP 3），与 JS 的 hourTop 同源
    hour_opts = "".join(
        f'<option value="{value}"'
        f'{" selected" if value == DEFAULT_HOUR_TOP else ""}>{label}</option>'
        for value, label in ((3, "TOP 3"), (5, "TOP 5"), (10, "TOP 10"), (0, "全部模型"))
    )
    ws_total = len(summary.by_workspace)
    ws_note = (
        f"共 {ws_total:,} 个工作空间 · 显示前 {min(DEFAULT_WS_TOP, ws_total)} 个"
        if ws_total else ""
    )

    payload = _payload(summary, records, palette, prices, generated,
                       window_days, custom_range)
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_js = data_js.replace("</", "<\\/")  # 防止日志内容提前闭合 <script>

    footer = (
        f"生成时间 {e(generated)} · 数据来自本机会话日志，不外发、无外部依赖<br>"
        "口径：请求级真实 usage；金额按牌价估算，缓存读命中走缓存价、缓存写入按输入价 ×1.25、"
        "其余输入走输入价，输出走输出价。不同套餐单价请用 --prices 覆盖；"
        "统计周期跟随全局时间窗口，空窗日不参与日均计算。<br>"
        "绿色系用于 UI 框架，厂商品牌色仅用于数据系列且始终附文字标签（WCAG 1.4.1）。"
        "未验证平台只表示「本机没有真实日志可供核对」，不代表功能已支持。"
    )
    subtitle = f"请求级真实 usage · 多平台统一口径 · 数据截至 {e(generated)}"

    # 无 JS 时静态首屏的卡片说明；数字与 JS renderDist 的默认 TOP 3 口径一致。
    dist_rows = [d for d in summary.distribution(top=DEFAULT_DIST_TOP)["models"] if d["count"]]
    dist_note = (
        f"TOP {len(dist_rows)} 模型 · 共 {sum(d['count'] for d in dist_rows):,} 次"
        if dist_rows else ""
    )

    css = (
        _CSS.replace("__SANS__", _SANS)
        .replace("__MONO__", _MONO)
        .replace("__LIGHT_CSS__", _vars(GREEN_LIGHT))
        .replace("__DARK_CSS__", _vars(GREEN_DARK))
        .replace("__HEAT_L_CSS__", _heat_css("light"))
        .replace("__HEAT_D_CSS__", _heat_css("dark"))
    )
    script_js = (_SCRIPT
                 .replace("__HEAT_L_JS__", _heat_json("light"))
                 .replace("__HEAT_D_JS__", _heat_json("dark"))
                 .replace("__DIST_TOP__", str(DEFAULT_DIST_TOP))
                 .replace("__WS_TOP__", str(DEFAULT_WS_TOP))
                 .replace("__HOUR_TOP__", str(DEFAULT_HOUR_TOP))
                 .replace("__VIEW_DAYS__", str(DEFAULT_VIEW_DAYS)))
    replacements = {
        "__TITLE__": e(title),
        "__SUBTITLE__": subtitle,
        "__THEME__": "light" if theme_name == "light" else "dark",
        "__GENERATED__": e(generated),
        "__CSS__": css,
        "__PERIODS__": period_pills,
        "__DAYVAL__": e(day_val),
        "__DAYMIN__": e(day_min),
        "__DAYMAX__": e(day_max),
        "__PLATOPTS__": plat_opts,
        "__WSOPTS__": ws_opts,
        "__HOUROPTS__": hour_opts,
        "__WSNOTE__": ws_note,
        "__HERO__": hero,
        "__KPIS__": kpis,
        "__MODELCAP__": (
            "同厂商模型用明度阶梯区分，色相保持品牌体系 · "
            f"全局 50% 单次请求 {fmt(summary.global_p50)}"
        ),
        "__MODELS__": _model_card(summary, palette),
        "__DAILY__": _daily_card(records, summary, palette),
        "__SOURCES__": _sources_card(statuses, imported),
        "__IMPORTED__": json.dumps(sorted(set(imported)), ensure_ascii=False),
        "__MODEL_TOTALS__": _model_totals_card(summary, palette),
        "__HOURLY__": _hourly_card(summary, palette),
        "__DISTNOTE__": dist_note,
        "__REQDIST__": _request_size_card(summary, palette),
        "__DAYHOUR__": _dayhour_card(summary, None if custom_range else generated[:10]),
        "__WORKSPACES__": _workspace_card(summary),
        "__FOOTER__": footer,
        "__DATA__": data_js,
        "__SCRIPT__": script_js,
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

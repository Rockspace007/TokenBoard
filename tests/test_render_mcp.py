# -*- coding: utf-8 -*-
"""渲染与 MCP 协议测试：绿色令牌、品牌色、离线约束、JSON-RPC 握手。"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tokenboard.aggregate import DEFAULT_HOUR_TOP, summarize  # noqa: E402
from tokenboard.brands import palette_for  # noqa: E402
from tokenboard.mcp_server import TOOLS, handle  # noqa: E402
from tokenboard.models import SourceStatus, UsageRecord  # noqa: E402
from tokenboard.render import _hourly_card, _workspace_card, render_html, summary_json  # noqa: E402

TS = 1762344000


def sample():
    records = [
        UsageRecord(ts=TS, platform="workbuddy", workspace="proj", session_id="s1",
                    model="deepseek-chat", input_tokens=1000, output_tokens=100,
                    cache_read_tokens=500, total_tokens=1100),
        UsageRecord(ts=TS + 3600, platform="claude_code", workspace="proj", session_id="s2",
                    model="claude-sonnet-4-5", input_tokens=500, output_tokens=50,
                    total_tokens=550),
    ]
    status = SourceStatus("workbuddy", "WorkBuddy", True, ("/tmp/projects",), 2, "已验证")
    return summarize(records), records, [status]


def call(message):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        handle(message)
    raw = buf.getvalue().strip()
    return json.loads(raw) if raw else None


class TestRender(unittest.TestCase):
    def setUp(self):
        self.summary, self.records, self.statuses = sample()

    def test_green_tokens_and_brand_colors(self):
        html = render_html(self.summary, self.records, self.statuses)
        self.assertIn("--bg:#0A0B0C", html, "暗夜玻璃深色令牌必须注入")
        self.assertIn("--brand:#D4FF2B", html, "深色主题荧光黄绿强调色必须注入")
        self.assertIn("#4D6BFE", html, "DeepSeek 品牌色应出现在数据系列")
        self.assertIn("#D97757", html, "Anthropic 品牌色应出现在数据系列")

    def test_light_theme(self):
        html = render_html(self.summary, self.records, theme_name="light")
        self.assertIn('data-theme="light"', html)
        self.assertIn("--bg:#FFFFFF", html)
        self.assertIn("--brand:#00E5A0", html)

    def test_new_modules_present(self):
        html = render_html(self.summary, self.records, self.statuses)
        for needle in ("单模型总量统计", "0—24 时分布 · 按模型",
                       "单次请求大小分布", "日活分布", "会话消耗活跃分布",
                       "周期跟随全局时间窗口", "metricSeg", "window.TB_DATA=",
                       "data-tip", "id=\"wsGran\"", "<span>平台</span>",
                       "class=\"wplat\""):
            self.assertIn(needle, html)

    def test_ws_granularity_heatmap(self):
        """分布列三档粒度下拉（当日 24 时 / 当周 7 天 / 当月），默认日档；一律按总量统计。"""
        html = render_html(self.summary, self.records, self.statuses)
        self.assertIn('id="wsGran"', html)
        self.assertIn('<option value="day" selected>日 · 当日 24 时</option>', html)
        for opt in ('<option value="week">周 · 当周 7 天</option>',
                    '<option value="month">月 · 当月</option>'):
            self.assertIn(opt, html)
        self.assertIn("wsGran='day'", html)
        self.assertIn("分布（日 · 24 时）", html)
        # 周档取锚点所在自然周（周一至周日），月档取当月天数
        self.assertIn("function weekSeq(a)", html)
        self.assertIn("weekSeq(a),hourly:false,label:'周 · 当周 7 天'", html)
        # 三档一律按总量时间周期显示：数据源取全量聚合桶，不随窗口变化
        self.assertIn("A.wsAll[w]", html)
        self.assertIn("A.sessAll[entry.i]", html)
        self.assertIn("var avgD=A.totAll/", html)
        self.assertNotIn('id="wsMult"', html)
        self.assertNotIn('id="wsPlats"', html)
        # Python 首屏占位格与默认粒度对齐：每行恰好 24 个 <i>
        card = _workspace_card(self.summary)
        row_count = card.count('class="wsrow click"')
        self.assertGreater(row_count, 0)
        self.assertEqual(card.count('<i style="flex:1;background:var(--brand)'),
                         24 * row_count)

    def test_hour_top_select_defaults_to_three(self):
        """0—24 时分布卡提供 TOP 3/5/10/全部 下拉，默认选中 TOP 3。"""
        html = render_html(self.summary, self.records, self.statuses)
        self.assertIn('id="hourTop"', html)
        self.assertIn('<option value="3" selected>TOP 3</option>', html)
        for value in ("5", "10", "0"):
            self.assertIn(f'<option value="{value}"', html)
        self.assertIn("全部模型", html)
        self.assertIn("var hourTop=3;", html)
        # 占位符漏替换会让页面 JS 直接语法错误，必须锁住
        self.assertNotIn("__HOUR_TOP__", html)
        self.assertNotIn("__HOUROPTS__", html)

    def test_hour_top_not_hardcoded_to_two(self):
        """曲线数量由 hourTop 控制且已绑定 change，不能回退成硬编码 2 条。"""
        html = render_html(self.summary, self.records, self.statuses)
        self.assertIn("hourTop>0?order.slice(0,hourTop):order", html)
        self.assertNotIn(".slice(0,2)", html)
        self.assertIn("$('#hourTop')", html)
        self.assertIn('class="hdtools"', html)

    def test_hour_mode_total_and_day(self):
        """0—24 时口径：累计=全部数据（不限窗口），仅当日=聚焦日；不再有「窗口累计」。"""
        html = render_html(self.summary, self.records, self.statuses)
        self.assertIn('<option value="all" selected>累计</option>', html)
        self.assertIn('<option value="today">仅当日</option>', html)
        self.assertNotIn("窗口累计", html)
        self.assertIn("var hourMode='all';", html)
        self.assertIn("A.hball", html)    # 全量逐时聚合桶（不受窗口限制）
        self.assertNotIn("A.hb[", html)   # 旧窗口口径聚合已移除

    def test_daily_heat_day_view_single_row(self):
        """日活分布「日」档只渲染锚点当日一行，其余日期不显示。"""
        html = render_html(self.summary, self.records, self.statuses)
        self.assertIn("var days=[focusDayKey()]", html)
        self.assertIn("仅当日一行", html)

    def test_detail_cards_use_total_scope(self):
        """明细卡一律按「总量」口径：工作空间/会话清单、单次请求大小分布、0—24 时累计档。"""
        html = render_html(self.summary, self.records, self.statuses)
        # 工作空间与会话清单按总量（占比分母用全量 A.totAll）
        self.assertIn("A.wsT[s.w].tt", html)
        self.assertIn("A.sessT.push", html)
        self.assertIn("pct(x.tt,A.totAll)", html)
        self.assertIn("A.totAll)", html)
        # 单次请求大小分布整卡按总量（含 TOP 排序与 50%/90% 分位）
        self.assertIn("A.sizesAll[mi]", html)
        self.assertIn("A.gp50All", html)
        # 0—24 时「累计」档的模型排序按全量
        self.assertIn("orderByTokensAll(A)", html)
        # 已被总量桶取代的窗口口径结构应清理干净
        for dead in ("A.sizes[", "A.gp50;", "A.ws[", "A.sess.push"):
            self.assertNotIn(dead, html)

    def test_daily_trend_total_caliber_and_span_toggle(self):
        """每日用量趋势按面板自身跨度独立口径渲染，并带 1日/3日/7日/本月 跨度下拉。"""
        html = render_html(self.summary, self.records, self.statuses)
        # 跨度控件：原按钮组改为 <select id="dailySpan">，默认选中 7日
        self.assertIn('id="dailySpan"', html)
        for opt in ('value="1">1日', 'value="3">3日',
                    'value="7" selected>7日', 'value="month">本月'):
            self.assertIn(opt, html)
        self.assertIn("var dailySpan='7';", html)
        # 数据源：全量逐日×模型桶 A.dmAll（仅受平台筛选），按跨度日期切片后使用
        self.assertIn("A.dmAll[dkA][r[1]]", html)
        self.assertIn("function dailyDays(A)", html)
        self.assertIn("orderByTokensAll(A)", html)   # 累计档 / 大小分布仍按总量排序
        # 每日柱模型集合改由本面板自己的「显示模型数量」下拉（dailyTop）控制，
        # 不再与左侧「按模型消耗」共用全局前 8；JS 初始值与 Python 常量同源。
        self.assertIn("function visibleModels(A){return orderByTokens(A).slice(0,8);}", html)
        self.assertIn('id="dailyTop"', html)              # 面板自带 TOP 下拉
        self.assertIn("var dailyTop=8;", html)            # JS 初始值（__DAILY_TOP__ 已替换为 DEFAULT_DAILY_TOP=8）
        self.assertIn('value="8" selected', html)          # 下拉默认 TOP 8 与 JS 初始值同源
        self.assertIn("var order=visibleModels(A);", html)  # modelRows 仍采用共用集合
        # 数值与模型 TOP 都按本卡片跨度独立统计，不借用窗口口径 A.mt
        self.assertIn("var spanDm={},spanMt=new Array(models.length).fill(0);", html)
        self.assertIn("var top=dailyTop>0?spanOrder.slice(0,dailyTop):spanOrder;", html)
        self.assertIn("var o=spanDm[dk];", html)             # 柱数据取跨度切片
        self.assertNotIn("var top=visibleModels(A);", html)   # 不再与左侧共用集合
        # 柱高基准只按可见模型累加，柱高才能跟随列表
        self.assertIn("top.forEach(function(mi){t+=o[mi]||0;});", html)
        # 本月/跨度改为连续日轴（当月1日→今日），不再依赖有数据日做过滤
        self.assertIn("endK=fm(t),loK;", html)
        self.assertIn("每日用量趋势", html)
        # 口径说明跟随跨度，不再挂「总量口径」
        self.assertIn("var spanLabel=dailySpan==='month'?'本月口径':(dailySpan+'日口径');", html)
        self.assertIn("7日口径 · 当前 TOP 8", html)          # 无 JS 时静态首屏初值
        self.assertNotIn("单位 Token · 总量口径", html)
        # 图例间距：作用域限定 #dailyChart，两行收紧(row-gap)、整块下沉离标题更松、
        # 与下方柱状图留足间距；不清染 0—24 时分布的通用 .legend。
        self.assertIn("#dailyChart .legend{row-gap:5px;column-gap:14px;margin-top:12px;margin-bottom:10px}", html)
        self.assertIn(".legend{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:8px}", html)

    def test_daily_bars_all_dates_and_compact_month(self):
        """每日柱每根都标日期；本月固定切「D日」短标并在横轴左端补「M月」角标。"""
        html = render_html(self.summary, self.records, self.statuses)
        # JS 版：移除旧的稀疏抽稀逻辑，改为每根柱都输出一个日期标签
        self.assertNotIn("var stepL=", html)                    # 旧的隔 N 根才标已移除
        self.assertIn("var compact=(dailySpan==='month')||(slot<28);", html)  # 本月强制短标
        self.assertIn("横轴左端红框位", html)                    # 月份角标落在横轴左端
        self.assertIn("var fs=slot<15?7:9;", html)              # 极密缩字号防重叠
        self.assertIn("compact?(parseInt(dk.slice(8),10)+'日'):dk.slice(5)", html)  # 短标/全标
        self.assertIn("+lastM+'月</text>'", html)                # 当月月份角标
        # 图例跟随共用集合，不再写死前 6
        self.assertIn("var legend=top.map(function(mi){", html)

    def test_static_daily_card_same_caliber(self):
        """静态降级首屏 _daily_card 与 JS 版同口径：跨度内 TOP 模型 + 每柱标日期 + 月份角标。"""
        import inspect
        from tokenboard import render as rmod
        src = inspect.getsource(rmod._daily_card)
        self.assertIn("span_mt", src)                            # 模型按跨度内消耗排序
        self.assertIn("if span_mt.get(m, 0) > 0", src)
        self.assertNotIn("summary.models[:DEFAULT_DAILY_TOP]", src)  # 不再借用全量排序
        self.assertIn("compact = slot < 28", src)                # 同一紧凑阈值
        self.assertIn("f'{int(day[8:])}日' if compact else day[5:]", src)  # 每柱标日期
        self.assertIn("f'font-weight=\"600\">{last_m}月</text>'", src)     # 月份角标
        self.assertIn('y="{base + 15}"', src)                    # 角标落在横轴左端

    def test_model_rows_platform_column(self):
        """按模型消耗行末新增「平台」列，展示该模型在哪些平台被使用。"""
        html = render_html(self.summary, self.records, self.statuses)
        self.assertIn('class="plats"', html)          # 平台列容器
        self.assertIn(".pchip{", html)               # 平台 chip 样式
        self.assertIn("A.modelPlats[mi]", html)       # 每模型平台集合聚合
        self.assertIn("plabel(pi)", html)            # 渲染平台名
        # 网格 4 列：轨道列用 1fr 弹性延长吃掉中段空白，数值/平台列固定宽并靠右贴边，
        # 平台 chip 右对齐；各行严格对齐，右侧不留白。
        self.assertIn("var(--nmw,200px) minmax(0,1fr) minmax(190px,200px) minmax(0,96px)", html)
        self.assertIn("justify-content:flex-end", html)   # 平台列贴右
        self.assertIn('<span class="plats"></span>', html)  # 静态降级首屏保持 4 列对齐

    def test_heat_level_follows_palette_length(self):
        """色阶档位不得超出色板长度：越界会取到 undefined，导致有数据的格子变透明。"""
        html = render_html(self.summary, self.records, self.statuses)
        self.assertIn("var top=Math.max(1,HEAT.length-1)", html)
        self.assertIn("(v>0?HEAT[heatLevel(v,avg)]:'var(--surface2)')", html)

    def test_hourly_card_follows_top_n(self):
        """首屏图例/曲线数跟随 top_n，0 表示全部模型（与 JS 口径一致）。"""
        models = ("deepseek-chat", "claude-sonnet-4-5", "gpt-4o",
                  "glm-4.6", "qwen-plus", "hy4-free")
        records = [
            UsageRecord(ts=TS + h * 3600, platform="workbuddy", workspace="proj",
                        session_id=f"s{i}", model=m, input_tokens=1000 * (i + 1),
                        output_tokens=100, total_tokens=1100 * (i + 1))
            for i, m in enumerate(models) for h in range(0, 24, 3)
        ]
        summary = summarize(records)
        palette = palette_for(summary.models)
        self.assertEqual(DEFAULT_HOUR_TOP, 3)
        for top_n, expected in ((1, 1), (3, 3), (5, 5), (10, 6), (0, 6)):
            with self.subTest(top_n=top_n):
                card = _hourly_card(summary, palette, top_n=top_n)
                self.assertEqual(card.count("data-dm="), expected)

    def test_payload_escapes_closing_script(self):
        r = UsageRecord(ts=TS, platform="p", workspace="</script><b>x</b>",
                        session_id="s", model="m", input_tokens=1, output_tokens=1)
        html = render_html(summarize([r]), [r])
        self.assertNotIn("</script><b>", html)

    def test_fully_offline_and_no_placeholders(self):
        html = render_html(self.summary, self.records, self.statuses)
        self.assertNotIn("https://", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("<script src", html)
        self.assertNotIn("__CSS__", html)
        self.assertNotIn("__HERO__", html)
        self.assertNotIn("__KPIS__", html)
        self.assertNotIn("__DAILY__", html)

    def test_unverified_label_visible(self):
        html = render_html(self.summary, self.records, self.statuses)
        self.assertIn("已验证", html)
        self.assertIn("数据源状态", html)

    def test_empty_summary_does_not_crash(self):
        html = render_html(summarize([]), [], [])
        self.assertIn("暂无数据", html)

    def test_html_escaping(self):
        r = UsageRecord(ts=TS, platform="p", workspace="<script>x</script>",
                        session_id="s", model="m", input_tokens=1, output_tokens=1)
        html = render_html(summarize([r]), [r])
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_summary_json(self):
        payload = json.loads(summary_json(self.summary, self.statuses))
        self.assertEqual(payload["kpi"]["requests"], 2)
        self.assertEqual(len(payload["models"]), 2)
        self.assertEqual(payload["sources"][0]["name"], "workbuddy")


class TestMCP(unittest.TestCase):
    def test_initialize(self):
        reply = call({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(reply["id"], 1)
        self.assertIn("serverInfo", reply["result"])
        self.assertEqual(reply["result"]["protocolVersion"], "2024-11-05")

    def test_tools_list(self):
        reply = call({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in reply["result"]["tools"]]
        self.assertIn("tokenboard_scan", names)
        self.assertIn("tokenboard_render", names)
        self.assertEqual(len(names), len(TOOLS))

    def test_notification_has_no_reply(self):
        self.assertIsNone(call({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_unknown_method(self):
        reply = call({"jsonrpc": "2.0", "id": 3, "method": "nope"})
        self.assertEqual(reply["error"]["code"], -32601)

    def test_tool_call_platforms(self):
        reply = call({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                      "params": {"name": "tokenboard_platforms", "arguments": {}}})
        body = reply["result"]["content"][0]["text"]
        self.assertIn("workbuddy", body)
        self.assertFalse(reply["result"]["isError"])

    def test_tool_call_unknown_tool_is_graceful(self):
        reply = call({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                      "params": {"name": "nope", "arguments": {}}})
        self.assertTrue(reply["result"]["isError"])


if __name__ == "__main__":
    unittest.main()

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
        """每日用量趋势按总量口径（A.dmAll）渲染，并带 1日/3日/7日/本月 跨度下拉。"""
        html = render_html(self.summary, self.records, self.statuses)
        # 跨度控件：原按钮组改为 <select id="dailySpan">，默认选中 7日
        self.assertIn('id="dailySpan"', html)
        for opt in ('value="1">1日', 'value="3">3日',
                    'value="7" selected>7日', 'value="month">本月'):
            self.assertIn(opt, html)
        self.assertIn("var dailySpan='7';", html)
        # 数据源切到总量口径：新增全量逐日×模型桶，渲染读取 A.dmAll
        self.assertIn("A.dmAll[dkA][r[1]]", html)
        self.assertIn("function dailyDays(A)", html)
        self.assertIn("orderByTokensAll(A)", html)   # 每日柱模型排序按总量
        # 本月/跨度改为连续日轴（当月1日→今日），不再依赖有数据日做过滤
        self.assertIn("endK=fm(t),loK;", html)
        self.assertIn("每日用量趋势", html)
        self.assertIn("总量口径", html)

    def test_model_rows_platform_column(self):
        """按模型消耗行末新增「平台」列，展示该模型在哪些平台被使用。"""
        html = render_html(self.summary, self.records, self.statuses)
        self.assertIn('class="plats"', html)          # 平台列容器
        self.assertIn(".pchip{", html)               # 平台 chip 样式
        self.assertIn("A.modelPlats[mi]", html)       # 每模型平台集合聚合
        self.assertIn("plabel(pi)", html)            # 渲染平台名
        # 网格新增第 4 列（平台），进度条轨道列已收窄为固定窄宽 minmax(72px,104px)
        self.assertIn("minmax(72px,104px)", html)

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

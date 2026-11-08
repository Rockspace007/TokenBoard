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
                       "单次请求大小分布", "日活分布", "工作空间活跃分布",
                       "周期跟随全局时间窗口", "metricSeg", "window.TB_DATA=",
                       "data-tip", "id=\"wsGran\""):
            self.assertIn(needle, html)

    def test_ws_granularity_heatmap(self):
        """分布列三档粒度下拉（日 24 时 / 周 7 天 / 月当月），默认周；首屏占位 7 格。"""
        html = render_html(self.summary, self.records, self.statuses)
        self.assertIn('id="wsGran"', html)
        self.assertIn('<option value="week" selected>周 · 7 天</option>', html)
        for opt in ('<option value="day">日 · 24 时</option>',
                    '<option value="month">月 · 当月</option>'):
            self.assertIn(opt, html)
        self.assertIn("wsGran='week'", html)
        self.assertIn("分布（周 · 近 7 天）", html)
        self.assertNotIn("分布（近 7 个有数据日）", html)
        self.assertNotIn('id="wsMult"', html)
        # Python 首屏占位格与默认粒度对齐：每行恰好 7 个 <i>
        card = _workspace_card(self.summary)
        row_count = card.count('class="wsrow click"')
        self.assertGreater(row_count, 0)
        self.assertEqual(card.count('<i style="flex:1;background:var(--brand)'),
                         7 * row_count)

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

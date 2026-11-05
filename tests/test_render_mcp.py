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

from tokenboard.aggregate import summarize  # noqa: E402
from tokenboard.mcp_server import TOOLS, handle  # noqa: E402
from tokenboard.models import SourceStatus, UsageRecord  # noqa: E402
from tokenboard.render import render_html, summary_json  # noqa: E402

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
        self.assertIn("--bg:#0E1A16", html, "深色绿主题令牌必须注入")
        self.assertIn("--brand:#1F6F63", html)
        self.assertIn("#4D6BFE", html, "DeepSeek 品牌色应出现在数据系列")
        self.assertIn("#D97757", html, "Anthropic 品牌色应出现在数据系列")

    def test_light_theme(self):
        html = render_html(self.summary, self.records, theme_name="light")
        self.assertIn('data-theme="light"', html)
        self.assertIn("--bg:#F5F7F6", html)

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

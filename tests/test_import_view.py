# -*- coding: utf-8 -*-
"""看板默认展示窗口与数据源「导入状态」列的回归测试。

锁住两个容易在后续迭代中被改坏的约定：
  1. 页面默认聚焦「1 天」，但 window_label/window_days 的 30 天口径必须保持
     ——它们还服务 agent_api 的 JSON / 简报，那里聚合的是全历史数据；
  2. 导入状态列存在、每行可点，且已导入平台显示「已验证」。
"""
from __future__ import annotations

import re
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tokenboard.aggregate import summarize  # noqa: E402
from tokenboard.cli import view_window, window_days, window_label  # noqa: E402
from tokenboard.models import SourceStatus  # noqa: E402
from tokenboard.render import (  # noqa: E402
    DEFAULT_VIEW_DAYS,
    DEFAULT_VIEW_LABEL,
    _sources_card,
    render_html,
)

STATUS = [
    SourceStatus(name="workbuddy", display_name="WorkBuddy", verified=True,
                 roots=("/tmp/wb",), file_count=3, note="ok"),
    SourceStatus(name="codex", display_name="OpenAI Codex CLI", verified=False,
                 roots=(), file_count=0, note="本机未安装"),
]


class ViewWindowTest(unittest.TestCase):
    def test_default_is_one_day(self):
        self.assertEqual((DEFAULT_VIEW_LABEL, DEFAULT_VIEW_DAYS), ("1 天", 1))
        self.assertEqual(view_window(None), ("1 天", 1))

    def test_agent_api_semantics_unchanged(self):
        """无 --since 时 JSON/简报仍标近 30 天，不能跟着页面一起变成 1 天。"""
        self.assertEqual(window_label(None), "近 30 天")
        self.assertEqual(window_days(None), 30)

    def test_explicit_since_keeps_label(self):
        since = int(datetime.now().timestamp() - 7 * 86400)
        self.assertEqual(view_window(since), ("近 7 天", 7))


class SourcesCardTest(unittest.TestCase):
    def test_column_and_buttons(self):
        html = _sources_card(STATUS)
        self.assertIn(">导入状态</th>", html)
        # 每行一个可点按钮；已验证行按钮带 ghost 样式，故按 data-plat 计数
        self.assertEqual(html.count('data-plat='), len(STATUS))
        self.assertIn('data-plat="codex"', html)
        self.assertIn('data-role="verify"', html)

    def test_verified_row_is_imported_by_default(self):
        """已验证平台的数据本来就在看板里，默认显示「已导入 / 重新导入」。"""
        html = _sources_card(STATUS)
        row = html.split("WorkBuddy", 1)[1].split("</tr>", 1)[0]
        self.assertIn("✓ 已导入", row)
        self.assertIn("重新导入", row)
        self.assertNotIn(">导入<", row)

    def test_unverified_row_is_pending_by_default(self):
        """未验证平台需用户点「导入」按需接入。"""
        html = _sources_card(STATUS)
        row = html.split("OpenAI Codex CLI", 1)[1].split("</tr>", 1)[0]
        self.assertIn("未导入", row)
        self.assertIn(">导入<", row)

    def test_imported_row_shows_verified(self):
        html = _sources_card(STATUS, imported=["codex"])
        row = html.split("OpenAI Codex CLI", 1)[1].split("</tr>", 1)[0]
        self.assertIn("✓ 已导入", row)
        self.assertIn("重新导入", row)
        self.assertIn('data-role="verify">已验证', row)


class RenderImportInjectionTest(unittest.TestCase):
    def test_imported_injected_into_page(self):
        html = render_html(summarize([]), [], STATUS, imported=["codex"])
        self.assertIn('window.TB_IMPORTED=["codex"]', html)
        self.assertNotIn("__IMPORTED__", html)
        self.assertIn(">导入状态</th>", html)

    def test_default_page_is_one_day(self):
        html = render_html(summarize([]), [], STATUS)
        self.assertIn('class="ppill on" data-w="1">1 天', html)
        # data_js 用紧凑 JSON（无空格），用正则兼容两种序列化格式
        self.assertRegex(html, r'"win":\s*1\b')


if __name__ == "__main__":
    unittest.main()

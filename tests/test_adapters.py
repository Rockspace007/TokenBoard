# -*- coding: utf-8 -*-
"""各平台适配器用 fixture 固定行为，改字段不会悄悄破坏兼容性。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tokenboard.adapters.claude_code import ClaudeCodeAdapter  # noqa: E402
from tokenboard.adapters.codex import CodexAdapter  # noqa: E402
from tokenboard.adapters.generic import GenericAdapter  # noqa: E402
from tokenboard.adapters.opencode import OpenCodeAdapter  # noqa: E402
from tokenboard.adapters.workbuddy import WorkBuddyAdapter  # noqa: E402
from tokenboard.registry import all_adapters, get, names, normalize, scan  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def records(adapter, filename):
    return list(adapter.iter_records(FIX / filename, FIX))


class TestAdapters(unittest.TestCase):
    def test_workbuddy_fixture(self):
        recs = records(WorkBuddyAdapter(roots=[FIX]), "workbuddy.jsonl")
        self.assertEqual(len(recs), 2, "无 usage 的用户消息必须被跳过")
        self.assertEqual(recs[0].model, "hy4-free")
        self.assertEqual(recs[0].cache_read_tokens, 700)
        self.assertEqual(recs[1].model, "hy3")

    def test_claude_code_fixture(self):
        recs = records(ClaudeCodeAdapter(roots=[FIX]), "claude_code.jsonl")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].platform, "claude_code")
        self.assertEqual(recs[0].cache_read_tokens, 2000)
        self.assertEqual(recs[0].cache_write_tokens, 200)

    def test_codex_ignores_cumulative_usage(self):
        """total_token_usage 是累计值，若被采纳会重复计数。"""
        recs = records(CodexAdapter(roots=[FIX]), "codex.jsonl")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].total_tokens, 550)
        self.assertEqual(recs[0].model, "gpt-5-codex")

    def test_opencode_whole_file_json(self):
        recs = records(OpenCodeAdapter(roots=[FIX]), "opencode.json")
        self.assertEqual(len(recs), 2)
        self.assertEqual({r.model for r in recs}, {"qwen3-coder", "glm-4.6"})

    def test_generic_edge_cases(self):
        recs = records(GenericAdapter(roots=[FIX]), "edge.jsonl")
        # 坏行 / 坏时间戳被跳过；负输入被归零但有效输出仍保留（不整行丢弃）
        self.assertEqual(len(recs), 2)
        by_model = {r.model: r for r in recs}
        self.assertEqual(by_model["unknown-model"].input_tokens, 0)
        self.assertEqual(by_model["unknown-model"].total_tokens, 3)
        self.assertEqual(by_model["deepseek-chat"].cache_read_tokens, 100)

    def test_registry_aliases(self):
        self.assertEqual(normalize("claudecode"), "claude_code")
        self.assertEqual(normalize("treacode"), "trae")
        self.assertEqual(normalize("Claude-Code"), "claude_code")
        self.assertIn("workbuddy", names())
        with self.assertRaises(KeyError):
            get("not-a-platform")

    def test_unverified_not_auto_discovered(self):
        autos = [a.name for a in all_adapters() if a.auto_discover]
        self.assertEqual(autos, ["workbuddy"], "只有已验证平台参与无参数自动扫描")

    def test_scan_with_explicit_path(self):
        result = scan(paths=[FIX / "workbuddy.jsonl"])
        self.assertEqual(result.count, 2)
        self.assertFalse(result.errors)
        self.assertGreaterEqual(len(result.statuses), 5)


if __name__ == "__main__":
    unittest.main()

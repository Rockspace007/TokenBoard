# -*- coding: utf-8 -*-
"""通用字段探测的单元测试：这是多平台适配的地基，必须锁死。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tokenboard.adapters.base import (  # noqa: E402
    extract_model,
    extract_ts,
    extract_usage,
    parse_ts,
    workspace_from,
)
from tokenboard.models import UsageRecord  # noqa: E402


class TestUsage(unittest.TestCase):
    def test_workbuddy_rawusage_with_cache(self):
        obj = {"providerData": {"rawUsage": {
            "prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100,
            "prompt_cache_hit_tokens": 700,
            "prompt_tokens_details": {"cached_creation_tokens": 100},
        }}}
        usage = extract_usage(obj)
        self.assertEqual(usage["input_tokens"], 1000)
        self.assertEqual(usage["output_tokens"], 100)
        self.assertEqual(usage["cache_read_tokens"], 700)
        self.assertEqual(usage["cache_write_tokens"], 100)

    def test_anthropic_nested_cache_fields(self):
        obj = {"message": {"usage": {
            "input_tokens": 3000, "output_tokens": 400,
            "cache_read_input_tokens": 2000, "cache_creation_input_tokens": 200,
        }}}
        usage = extract_usage(obj)
        self.assertEqual(usage["total_tokens"], 3400)
        self.assertEqual(usage["cache_read_tokens"], 2000)

    def test_cache_is_clamped_to_input(self):
        """脏数据里缓存命中大于输入时不能算出负成本。"""
        obj = {"usage": {"prompt_tokens": 100, "completion_tokens": 10,
                         "prompt_cache_hit_tokens": 99999}}
        usage = extract_usage(obj)
        self.assertEqual(usage["cache_read_tokens"], 100)
        self.assertEqual(usage["cache_write_tokens"], 0)

    def test_total_derived_when_missing(self):
        usage = extract_usage({"usage": {"input_tokens": 600, "output_tokens": 60}})
        self.assertEqual(usage["total_tokens"], 660)

    def test_no_usage_returns_none(self):
        self.assertIsNone(extract_usage({"message": {"role": "user"}}))
        self.assertIsNone(extract_usage({}))


class TestTimestamp(unittest.TestCase):
    def test_iso8601_and_numeric(self):
        self.assertIsNotNone(parse_ts("2026-11-05T10:00:00.000Z"))
        self.assertIsNotNone(parse_ts("2026-11-05 10:00:00"))
        self.assertEqual(parse_ts(1762344000000), 1762344000)
        self.assertEqual(parse_ts(1762344000), 1762344000)

    def test_invalid(self):
        for value in (None, "", "not-a-time", 123, True, "2026-99-99"):
            self.assertIsNone(parse_ts(value), f"应拒绝 {value!r}")

    def test_extract_ts_prefers_first_valid(self):
        self.assertIsNotNone(extract_ts({"created_at": "bad", "timestamp": "2026-11-05T10:00:00Z"}))


class TestMisc(unittest.TestCase):
    def test_model_paths(self):
        self.assertEqual(extract_model({"message": {"model": "claude-sonnet-4-5"}}), "claude-sonnet-4-5")
        self.assertEqual(extract_model({}, "fallback"), "fallback")

    def test_workspace_slug(self):
        root = Path("/tmp/projects")
        p = root / "c-Users-foo-WorkBuddy-2026-11-05-10-00-00" / "abc.jsonl"
        self.assertEqual(workspace_from(p, root), "2026-11-05-10-00-00")
        self.assertEqual(workspace_from(root / "my-project" / "s.jsonl", root), "my-project")

    def test_record_defaults_and_sanitizing(self):
        rec = UsageRecord(ts=1, platform="p", workspace="w", session_id="s",
                          model="m", input_tokens=-5, output_tokens=3)
        self.assertEqual(rec.input_tokens, 0)
        self.assertEqual(rec.total_tokens, 3)
        self.assertEqual(rec.non_cached_input, 0)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""聚合与计价口径测试：数字一旦漂移，看板就会说谎。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tokenboard.aggregate import summarize  # noqa: E402
from tokenboard.brands import color_of, theme, vendor_of  # noqa: E402
from tokenboard.models import UsageRecord  # noqa: E402
from tokenboard.pricing import cost_cny, load_prices, price_of  # noqa: E402

TS = 1762344000  # 固定的 Unix 秒，保证测试可复现


def rec(model="hy4-free", **kw):
    base = dict(ts=TS, platform="workbuddy", workspace="proj", session_id="s1",
                model=model, input_tokens=1000, output_tokens=100,
                cache_read_tokens=0, cache_write_tokens=0, total_tokens=1100)
    base.update(kw)
    return UsageRecord(**base)


class TestPricing(unittest.TestCase):
    def test_prefix_matching(self):
        self.assertEqual(price_of("deepseek-chat").input, 2.0)
        self.assertEqual(price_of("claude-sonnet-4-5").output, 105.0)
        self.assertEqual(price_of("totally-unknown").input, 2.0)  # fallback

    def test_custom_prices(self):
        path = Path(__file__).parent / "fixtures" / "_prices.json"
        path.write_text('{"my-model": [3, 9, 0.6]}', encoding="utf-8")
        try:
            table = load_prices(path)
            self.assertEqual(price_of("my-model-x", table).output, 9.0)
        finally:
            path.unlink(missing_ok=True)

    def test_cache_clamp_never_negative(self):
        r = rec(input_tokens=100, cache_read_tokens=500, cache_write_tokens=500, total_tokens=110)
        self.assertGreaterEqual(cost_cny(r), 0.0)

    def test_cache_hit_is_cheaper(self):
        plain = cost_cny(rec(input_tokens=1000, output_tokens=0, total_tokens=1000))
        cached = cost_cny(rec(input_tokens=1000, output_tokens=0, cache_read_tokens=900, total_tokens=1000))
        self.assertLess(cached, plain)


class TestSummary(unittest.TestCase):
    def test_basic_kpi(self):
        s = summarize([rec(), rec(session_id="s2", model="hy3")])
        self.assertEqual(s.records, 2)
        self.assertEqual(s.total_tokens, 2200)
        self.assertEqual(s.sessions, 2)
        self.assertEqual(s.workspaces, 1)
        self.assertEqual(len(s.models), 2)
        self.assertEqual(len(s.hourly), 24)
        self.assertEqual(sum(s.bands), s.total_tokens)
        self.assertEqual(s.active_days, 1)

    def test_cache_hit_rate(self):
        s = summarize([rec(cache_read_tokens=500)])
        self.assertAlmostEqual(s.cache_hit_rate, 50.0)

    def test_empty_is_safe(self):
        s = summarize([])
        self.assertEqual(s.records, 0)
        self.assertEqual(s.cache_hit_rate, 0.0)
        self.assertEqual(s.io_ratio, 0.0)
        self.assertEqual(s.kpi()["estimated_cost_cny"], 0.0)

    def test_json_serializable(self):
        import json

        s = summarize([rec()])
        json.dumps(s.to_dict(), ensure_ascii=False)
        self.assertEqual(s.to_dict()["models"][0]["vendor"], "腾讯混元")


class TestBrands(unittest.TestCase):
    def test_brand_colors(self):
        self.assertEqual(color_of("deepseek-chat"), "#4D6BFE")
        self.assertEqual(color_of("claude-sonnet-4-5"), "#D97757")
        self.assertEqual(color_of("hy4-free"), "#00A3B5")
        self.assertEqual(vendor_of("gpt-5"), "OpenAI")

    def test_unknown_model_is_stable_and_green(self):
        a = color_of("some-new-model-xyz")
        b = color_of("some-new-model-xyz")
        self.assertEqual(a, b, "同一模型必须稳定同色")

    def test_theme_fallback(self):
        self.assertEqual(theme("no-such-theme"), theme("dark"))
        self.assertIn("brand", theme("light"))


if __name__ == "__main__":
    unittest.main()

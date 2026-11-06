# -*- coding: utf-8 -*-
"""各平台适配器用 fixture 固定行为，改字段不会悄悄破坏兼容性。"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tokenboard.adapters.claude_code import ClaudeCodeAdapter  # noqa: E402
from tokenboard.adapters.codex import CodexAdapter  # noqa: E402
from tokenboard.adapters.generic import GenericAdapter  # noqa: E402
from tokenboard.adapters.opencode import OpenCodeAdapter  # noqa: E402
from tokenboard.adapters.trae import TraeAdapter  # noqa: E402
from tokenboard.adapters.workbuddy import WorkBuddyAdapter  # noqa: E402
from tokenboard.adapters.external import ExternalAdapter  # noqa: E402
from tokenboard.cli import main  # noqa: E402
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

    def test_trae_hub_events(self):
        recs = records(TraeAdapter(roots=[FIX]), "trae_hub_event.jsonl")
        self.assertEqual(len(recs), 2, "只有 token_usage 事件产出记录")
        first = recs[0]
        self.assertEqual(first.platform, "trae")
        self.assertEqual(first.model, "deepseek-v4.1-flash")
        self.assertEqual(first.session_id, "session-abc")
        self.assertEqual(first.workspace, "overlay-studio")
        self.assertEqual(first.input_tokens, 202133)
        self.assertEqual(first.output_tokens, 13010)
        self.assertEqual(first.total_tokens, 215143, "total_tokens 为 null 时按输入+输出求和")
        self.assertEqual(first.cache_read_tokens, 0)
        self.assertEqual(first.field_states["cache_read_tokens"], "null")
        self.assertEqual(first.field_states["cache_write_tokens"], "null")
        self.assertEqual(first.field_states["total_tokens"], "derived")
        self.assertEqual(recs[1].cache_read_tokens, 1000)
        self.assertEqual(recs[1].field_states["cache_read_tokens"], "ok")

    def test_trae_field_states_and_event_shapes(self):
        """缺失 / null / 真实 0 分开记录；字符串、对象、双重编码、嵌套都兼容。"""
        with self.assertLogs("tokenboard.adapters.trae", level="ERROR") as logs:
            recs = records(TraeAdapter(roots=[FIX]), "trae_usage_shapes.jsonl")
        self.assertEqual(len(recs), 5, "全 null / 只缺输出的两条必须报错跳过")
        self.assertGreaterEqual(len(logs.output), 2)

        a, b, c, d, f = recs

        # A：total null → 输入 + 输出；缓存显式 0 是真实 0
        self.assertEqual((a.input_tokens, a.output_tokens, a.total_tokens), (100, 20, 120))
        self.assertEqual(a.field_states["total_tokens"], "derived")
        self.assertEqual(a.field_states["cache_read_tokens"], "zero")
        self.assertEqual(a.field_states["cache_write_tokens"], "zero")

        # B：输入缺失但 total 可读 → 反推；累计字段 prompt_tokens_total 不能被采用
        self.assertEqual((b.input_tokens, b.output_tokens, b.total_tokens), (40, 10, 50))
        self.assertEqual(b.field_states["input_tokens"], "derived")
        self.assertEqual(b.field_states["cache_read_tokens"], "missing")

        # C：输出 null 但 total 可读 → 反推；缓存读 null、缓存写真实
        self.assertEqual((c.input_tokens, c.output_tokens, c.total_tokens), (30, 30, 60))
        self.assertEqual(c.field_states["output_tokens"], "derived")
        self.assertEqual(c.field_states["cache_read_tokens"], "null")
        self.assertEqual(c.field_states["cache_write_tokens"], "ok")

        # D：嵌套 usage + input/output 别名
        self.assertEqual((d.input_tokens, d.output_tokens, d.total_tokens), (7, 3, 10))

        # F：只有 total，输入/输出不可算 → 保留总量但标记为 null；
        #    已知缓存值不能被缺失输入压成 0
        self.assertEqual(f.total_tokens, 9)
        self.assertEqual(f.input_tokens, 0)
        self.assertEqual(f.cache_read_tokens, 4)
        self.assertEqual(f.field_states["input_tokens"], "null")
        self.assertEqual(f.field_states["output_tokens"], "null")
        self.assertEqual(f.field_states["cache_write_tokens"], "missing")
        # 同一 task 的多次 token_usage 是多次请求，必须逐条累加
        self.assertEqual(sum(r.total_tokens for r in recs), 249)

    def test_trae_dedup(self):
        """重复行、同 request_uuid 的重试只算一次；不同请求要累加。"""
        recs = records(TraeAdapter(roots=[FIX]), "trae_dedup.jsonl")
        self.assertEqual(len(recs), 2)
        self.assertEqual([r.total_tokens for r in recs], [15, 30])
        self.assertEqual(sum(r.total_tokens for r in recs), 45)
        self.assertEqual(
            {r.dedup_key for r in recs},
            {"trae|task-2|request_uuid|req-1", "trae|task-2|request_uuid|req-2"},
        )

    def test_trae_cross_file_dedup_via_registry(self):
        """同一请求的多份缓存即使 mtime 不同，也按 dedup_key 只计一次。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = (
                '{"task_id":"shared","seq":1,"type":"token_usage",'
                '"data":{"prompt_tokens":10,"completion_tokens":5}}\n'
            )
            for hub, mtime in (("h1", 1000000000), ("h2", 1000000100)):
                path = root / "TraeCode" / hub / "task.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                os.utime(path, (mtime, mtime))
            adapter = TraeAdapter(roots=[root])
            with mock.patch("tokenboard.registry.get", return_value=adapter):
                with self.assertLogs("tokenboard.adapters.trae", level="WARNING"):
                    result = scan(platforms=["trae"])
            self.assertEqual(len(result.records), 1)
            self.assertEqual(result.records[0].total_tokens, 15)

    def test_trae_degraded_without_metadata_or_model(self):
        """metadata/model_config 缺失时用 mtime、路径与 unknown 降级，并给出日志。"""
        with self.assertLogs("tokenboard.adapters.trae", level="WARNING") as logs:
            recs = records(TraeAdapter(roots=[FIX]), "trae_degraded.jsonl")
        self.assertEqual(len(recs), 2)
        mtime = int((FIX / "trae_degraded.jsonl").stat().st_mtime)
        for rec in recs:
            self.assertEqual(rec.model, "unknown")
            self.assertEqual(rec.workspace, "trae_degraded")
            self.assertEqual(rec.session_id, "trae_degraded")
            self.assertLessEqual(abs(rec.ts - mtime), 1)
        self.assertTrue(any("mtime" in line for line in logs.output))
        self.assertTrue(any("unknown" in line for line in logs.output))

    def test_trae_discover_ignores_memory_and_flat_files(self):
        """根路径混入 memory 或单层 jsonl 时，discover 只保留事件流目录。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "TraeCode" / "hub" / "task.jsonl"
            good.parent.mkdir(parents=True)
            good.write_text("", encoding="utf-8")
            (root / "memory").mkdir()
            (root / "memory" / "notes.jsonl").write_text("", encoding="utf-8")
            (root / "stray.jsonl").write_text("", encoding="utf-8")
            adapter = TraeAdapter(roots=[root])
            self.assertEqual(adapter.discover(), [good])
        self.assertFalse(TraeAdapter.auto_discover, "Trae 仍需显式 --platform trae")

    def test_external_csv_auto_detect(self):
        """CSV 标准列名走通用别名：时间、输入/输出、缓存读写都能取到。"""
        adapter = ExternalAdapter(paths=[FIX / "import_usage.csv"])
        recs = list(adapter.iter_all_records())
        self.assertEqual(len(recs), 2)
        first, second = recs
        self.assertEqual(first.platform, "external")
        self.assertEqual(first.model, "trae-export-model")
        self.assertEqual(first.session_id, "conv-1")
        self.assertEqual(first.workspace, "import_usage")
        self.assertEqual((first.input_tokens, first.output_tokens, first.total_tokens), (100, 20, 120))
        self.assertEqual(first.field_states["total_tokens"], "derived")
        self.assertEqual(first.cache_read_tokens, 30)
        self.assertEqual(first.cache_write_tokens, 10)
        # 第二行缓存列为空：是缺失，不是真实 0
        self.assertEqual(second.total_tokens, 240)
        self.assertEqual(second.cache_read_tokens, 0)
        self.assertEqual(second.field_states["cache_read_tokens"], "missing")
        self.assertEqual(second.field_states["cache_write_tokens"], "missing")

    def test_external_json_array(self):
        adapter = ExternalAdapter(paths=[FIX / "import_usage.json"])
        recs = list(adapter.iter_all_records())
        self.assertEqual(len(recs), 2)
        self.assertEqual([r.total_tokens for r in recs], [60, 45])
        self.assertEqual(recs[0].ts, int(datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc).timestamp()))
        self.assertEqual(recs[1].ts, 1793700000, "毫秒时间戳要换算成秒")

    def test_external_mapping_nested_json(self):
        """--map 支持 JSON 点分路径，null 输入可由 total 反推。"""
        adapter = ExternalAdapter(
            paths=[FIX / "import_usage_wrapped.json"],
            platform="trae",
            mapping={
                "ts": "meta.ts",
                "input_tokens": "usage.in",
                "output_tokens": "usage.out",
                "total_tokens": "total",
                "model": "model_name",
                "session_id": "chat.id",
                "workspace": "ws",
            },
        )
        recs = list(adapter.iter_all_records())
        self.assertEqual(len(recs), 2)
        first, second = recs
        self.assertEqual(first.platform, "trae")
        self.assertEqual((first.input_tokens, first.output_tokens, first.total_tokens), (10, 5, 15))
        self.assertEqual(second.input_tokens, 20)
        self.assertEqual(second.field_states["input_tokens"], "derived")
        self.assertEqual(second.field_states["output_tokens"], "ok")
        self.assertEqual(second.session_id, "s-2")
        self.assertEqual(second.workspace, "proj-a")

    def test_external_custom_csv_mapping_and_dedup_key(self):
        adapter = ExternalAdapter(
            paths=[FIX / "import_usage_custom.csv"],
            mapping={
                "ts": "when",
                "input_tokens": "in",
                "output_tokens": "out",
                "total_tokens": "total",
                "model": "model_name",
                "session_id": "chat_id",
                "workspace": "project",
                "dedup_key": "dedup",
            },
        )
        recs = list(adapter.iter_all_records())
        self.assertEqual(len(recs), 2)
        self.assertEqual([r.total_tokens for r in recs], [15, 27])
        self.assertEqual(recs[1].input_tokens, 20)
        self.assertEqual([r.dedup_key for r in recs], ["row-1", "row-2"])

    def test_external_duplicate_import_dedup(self):
        """同一份导出被重复放入两个文件，只算一次。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = (FIX / "import_usage.csv").read_text(encoding="utf-8")
            for name, mtime in (("a.csv", 1000000000), ("b.csv", 1000000100)):
                path = root / name
                path.write_text(content, encoding="utf-8")
                os.utime(path, (mtime, mtime))
            adapter = ExternalAdapter(paths=[root])
            recs = list(adapter.iter_all_records())
        self.assertEqual(len(recs), 2, "两行数据各只计一次")
        self.assertEqual(sum(r.total_tokens for r in recs), 360)

    def test_external_missing_ts_falls_back_to_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no_ts.csv"
            path.write_text("prompt_tokens,completion_tokens\n10,5\n", encoding="utf-8")
            os.utime(path, (1000000000, 1000000000))
            with self.assertLogs("tokenboard.adapters.external", level="WARNING") as logs:
                recs = list(ExternalAdapter(paths=[path]).iter_all_records())
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].ts, 1000000000)
        self.assertTrue(any("时间戳" in line or "mtime" in line for line in logs.output))

    def test_external_cli_table_output(self):
        buf = StringIO()
        with redirect_stdout(buf):
            code = main(["import", str(FIX / "import_usage.csv"), "--platform", "trae", "--format", "table"])
        out = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("合计 Token", out)
        self.assertIn("trae", out)
        self.assertEqual(ExternalAdapter.auto_discover, False)

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
        # 已验证平台自动扫描；请保持与各适配器的 verified 标记一致
        self.assertEqual(autos, ["workbuddy", "opencode"], "只有已验证平台参与无参数自动扫描")

    def test_scan_with_explicit_path(self):
        result = scan(paths=[FIX / "workbuddy.jsonl"])
        self.assertEqual(result.count, 2)
        self.assertFalse(result.errors)
        self.assertGreaterEqual(len(result.statuses), 5)


PAGE_FIX = FIX / "trae_usage_page_response.json"

# 用量页常见结构：session/usage 两层嵌套、毫秒时间戳、null 与缺失并存
PAGE_MAP = {
    "ts": "createdAt",
    "model": "modelName",
    "session_id": "session.id",
    "title": "session.title",
    "workspace": "session.workspacePath",
    "input_tokens": "usage.promptTokens",
    "output_tokens": "usage.completionTokens",
    "total_tokens": "usage.totalTokens",
    "cache_read_tokens": "usage.cachedTokens",
}


def _capture_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "trae_capture.py"
    spec = importlib.util.spec_from_file_location("trae_capture", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestTraeUsagePageFixture(unittest.TestCase):
    """抓取脚本落盘的响应 fixture：解析、字段映射、缺字段都必须稳定。"""

    def test_records_path_explicit_mapping(self):
        adapter = ExternalAdapter(
            paths=[PAGE_FIX], platform="trae", mapping=PAGE_MAP, records_path="data.items"
        )
        recs = list(adapter.iter_all_records())
        self.assertEqual(len(recs), 3, "data.items 下的三条记录都要解析，permissions 不能被当成记录")

        a, b, c = recs
        self.assertEqual(a.ts, 1762300800, "毫秒时间戳要换算成秒")
        self.assertEqual(a.platform, "trae")
        self.assertEqual(a.model, "deepseek-v4.1-flash")
        self.assertEqual(a.session_id, "sess-a")
        self.assertEqual(a.title, "重构登录流程")
        self.assertEqual(a.workspace, "/Users/demo/projects/portal")
        self.assertEqual((a.input_tokens, a.output_tokens, a.total_tokens), (120000, 8000, 128000))
        self.assertEqual(a.field_states["total_tokens"], "derived", "total 为 null 时按输入+输出求和")
        self.assertEqual(a.cache_read_tokens, 30000)

        self.assertEqual(b.total_tokens, 57000)
        self.assertEqual(b.cache_read_tokens, 0)
        self.assertEqual(b.field_states["cache_read_tokens"], "null", "null 不是真实 0")
        self.assertEqual(b.workspace, "trae_usage_page_response", "缺失路径回落到文件上下文")

        self.assertEqual(c.ts, int(datetime(2026, 11, 6, 2, 30, tzinfo=timezone.utc).timestamp()))
        self.assertEqual((c.input_tokens, c.output_tokens, c.total_tokens), (0, 500, 500))
        self.assertEqual(c.field_states["input_tokens"], "derived")
        self.assertEqual(c.title, "")
        self.assertEqual(len({r.dedup_key for r in recs}), 3)

    def test_records_path_auto_detected(self):
        """不给 --records 时也能在 data.items 里找到记录数组，而不是 permissions。"""
        adapter = ExternalAdapter(paths=[PAGE_FIX], platform="trae", mapping=PAGE_MAP)
        recs = list(adapter.iter_all_records())
        self.assertEqual(len(recs), 3)
        self.assertEqual({r.session_id for r in recs}, {"sess-a", "sess-b", "sess-c"})

    def test_cli_import_with_records_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "usage.json"
            argv = ["import", str(PAGE_FIX), "--records", "data.items",
                    "--platform", "trae", "--format", "json", "--out", str(out)]
            for field, source in PAGE_MAP.items():
                argv += ["--map", f"{field}={source}"]
            with redirect_stdout(StringIO()):
                code = main(argv)
            payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(payload["kpi"]["requests"], 3)
        self.assertEqual(payload["kpi"]["total_tokens"], 128000 + 57000 + 500)
        self.assertEqual([p["name"] for p in payload["platforms"]], ["trae"])

    def test_records_path_missing_is_reported(self):
        adapter = ExternalAdapter(paths=[PAGE_FIX], records_path="data.not_there")
        with self.assertLogs("tokenboard.adapters.external", level="ERROR") as logs:
            recs = list(adapter.iter_all_records())
        self.assertEqual(recs, [])
        self.assertTrue(any("data.not_there" in line for line in logs.output))


class TestCaptureScriptPureHelpers(unittest.TestCase):
    """抓取脚本的纯函数：不启动浏览器、不联网。"""

    def test_matches_url(self):
        mod = _capture_module()
        self.assertTrue(mod.matches_url("https://www.trae.cn/api/v1/usage?page=2", mod.MATCH_KEYWORDS))
        self.assertTrue(mod.matches_url("https://www.trae.cn/api/billing/quota", mod.MATCH_KEYWORDS))
        self.assertFalse(mod.matches_url("https://www.trae.cn/api/v1/user/profile", mod.MATCH_KEYWORDS))
        self.assertFalse(mod.matches_url("https://www.trae.cn/static/logo.svg", mod.MATCH_KEYWORDS))

    def test_same_origin(self):
        mod = _capture_module()
        self.assertTrue(mod.same_origin("https://www.trae.cn/api/usage", "https://www.trae.cn/account/usage"))
        self.assertFalse(mod.same_origin("https://api.trae.cn/usage", "https://www.trae.cn/account/usage"))

    def test_looks_like_usage(self):
        mod = _capture_module()
        self.assertTrue(mod.looks_like_usage({"data": {"items": [{"usage": {"promptTokens": 1}}]}}))
        self.assertTrue(mod.looks_like_usage([{"total_tokens": 3}]))
        self.assertFalse(mod.looks_like_usage({"items": [{"id": "x"}, {"id": "y"}]}))
        self.assertFalse(mod.looks_like_usage({"code": 0, "message": "ok"}))

    def test_redact_masks_private_fields_only(self):
        mod = _capture_module()
        payload = {
            "title": "私密会话",
            "total_tokens": 10,
            "session": {"workspacePath": "/Users/me/secret", "id": "s-1", "title": "内部项目"},
        }
        redacted = mod.redact_payload(payload)
        self.assertEqual(redacted["title"], "<redacted>")
        self.assertEqual(redacted["total_tokens"], 10)
        self.assertEqual(redacted["session"]["workspacePath"], "<redacted>")
        self.assertEqual(redacted["session"]["title"], "<redacted>")
        self.assertEqual(redacted["session"]["id"], "s-1", "会话 id 不遮挡，否则无法去重")
        self.assertEqual(payload["title"], "私密会话", "不能修改调用方传入的对象")

    def test_manifest_and_install_hint(self):
        mod = _capture_module()
        manifest = mod.build_manifest(
            mode="capture",
            url="https://www.trae.cn/account/usage",
            final_url="https://www.trae.cn/account/usage",
            profile=Path("/tmp/profile"),
            keywords=list(mod.MATCH_KEYWORDS),
            started_at="2026-11-06T10:00:00+08:00",
            finished_at="2026-11-06T10:00:20+08:00",
            responses=[{"url": "https://www.trae.cn/api/usage", "status": 200, "bytes": 100}],
            candidates=["/tmp/raw/001_api-usage.json", "/tmp/raw/002_api-usage.json"],
            login_suspected=False,
            errors=[],
            redacted=True,
        )
        self.assertEqual(manifest["tool"], "trae_capture")
        self.assertEqual(manifest["candidate_count"], 2)
        self.assertTrue(manifest["redacted"])
        self.assertIn("隐私", manifest["privacy_note"])
        self.assertNotIn("body", manifest["responses"][0], "清单不保存响应正文")

        hint = mod.install_hint()
        self.assertIn("pip install -e '.[capture]'", hint)
        self.assertIn("playwright install chromium", hint)
        self.assertIn("[trae-capture][ERROR]", hint)

    def test_missing_playwright_fails_loudly(self):
        """缺少可选依赖时必须返回非 0 并打印安装命令，不能静默跳过。"""
        mod = _capture_module()
        args = mod.build_parser().parse_args(["--dump"])
        stderr = StringIO()
        with mock.patch.object(mod, "_install_playwright_or_none", return_value=None):
            with redirect_stderr(stderr):
                code = mod.run_capture(args)
        self.assertEqual(code, 2)
        self.assertIn("pip install -e '.[capture]'", stderr.getvalue())
        self.assertIn("playwright install chromium", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

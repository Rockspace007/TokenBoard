# -*- coding: utf-8 -*-
"""OpenCode 适配器测试：临时构造 V2 SQLite 会话库，核对真实口径换算。

口径要点（与本机真实数据核对过）：
  * tokens.input 不含缓存 → UsageRecord 用包含口径（input = input + cache.read + cache.write）；
  * tokens.reasoning 与 tokens.output 不相交 → output = output + reasoning；
  * 子代理会话（parent_id）归属父会话，workspace 取 session.directory 的目录名。
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tokenboard.adapters.opencode import OpenCodeAdapter
from tokenboard.agent_api import report, summarize_records, usage_summary
from tokenboard.models import UsageRecord

_DDL_SESSION = """
CREATE TABLE session_v2 (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    directory TEXT,
    title TEXT,
    time_created INTEGER,
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    tokens_reasoning INTEGER DEFAULT 0,
    tokens_cache_read INTEGER DEFAULT 0,
    tokens_cache_write INTEGER DEFAULT 0,
    cost REAL DEFAULT 0
)
"""
_DDL_MESSAGE = """
CREATE TABLE session_message (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    type TEXT NOT NULL,
    seq INTEGER,
    time_created INTEGER,
    time_updated INTEGER,
    data TEXT NOT NULL
)
"""


def _msg(tokens: dict | None, model: str = "glm-4.7-flash", ts_ms: int = 1793955262511,
         agent: str = "build") -> str:
    data: dict = {
        "time": {"created": ts_ms},
        "agent": agent,
        "model": {"id": model, "providerID": "opencode", "variant": "max"},
        "content": [],
    }
    if tokens is not None:
        data["tokens"] = tokens
    return json.dumps(data, ensure_ascii=False)


def _make_db(dir_path: Path) -> Path:
    """两个会话：ses_parent（父）+ ses_child（子代理）。三条 assistant 消息。"""
    db = dir_path / "opencode.db"
    conn = sqlite3.connect(db)
    conn.execute(_DDL_SESSION)
    conn.execute(_DDL_MESSAGE)
    conn.executemany(
        "INSERT INTO session_v2 (id, parent_id, directory, title, time_created) VALUES (?,?,?,?,?)",
        [
            ("ses_parent", None, "/Users/mac/Rock/DevelopmentProject/TokenBoard", "顶层任务", 1793955000000),
            ("ses_child", "ses_parent", "/Users/mac/Rock/DevelopmentProject/TokenBoard", "子代理任务", 1793956000000),
        ],
    )
    conn.executemany(
        "INSERT INTO session_message (id, session_id, type, time_created, data) VALUES (?,?,?,?,?)",
        [
            # OpenCode 口径：input=100（不含缓存），read=40；output=50 reasoning=30
            ("msg_1", "ses_parent", "assistant", 1793955262511,
             _msg({"input": 100, "output": 50, "reasoning": 30, "cache": {"read": 40, "write": 0}})),
            # 全零占位行 → 应被跳过
            ("msg_2", "ses_child", "assistant", 1793956100000,
             _msg({"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}})),
            # 缺 tokens 的异常行 → 应被跳过
            ("msg_3", "ses_child", "assistant", 1793956200000, _msg(None)),
            # reasoning > output（不相交口径的真实形态）
            ("msg_4", "ses_child", "assistant", 1793956300000,
             _msg({"input": 500, "output": 5, "reasoning": 300, "cache": {"read": 900, "write": 0}},
                  model="deepseek-v4.1")),
        ],
    )
    conn.commit()
    conn.close()
    return db


class OpenCodeAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="tokenboard-test-")
        self.root = Path(self._tmp.name)
        self.db = _make_db(self.root)
        self.adapter = OpenCodeAdapter(roots=[str(self.root)])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _records(self) -> list[UsageRecord]:
        files = self.adapter.discover()
        self.assertEqual([f.name for f in files], ["opencode.db"])
        return list(self.adapter.iter_records(files[0], self.root))

    def test_discover_finds_sqlite_session_db(self) -> None:
        self.assertEqual(len(self.adapter.discover()), 1)

    def test_request_level_inclusive_mapping(self) -> None:
        records = self._records()
        self.assertEqual(len(records), 2)  # 全零行 + 缺 tokens 行都被跳过

        rec = records[0]
        # input 含缓存口径：100 + 40(read) + 0(write)
        self.assertEqual(rec.input_tokens, 140)
        # output 含 reasoning：50 + 30（两者不相交，必须相加才不漏计）
        self.assertEqual(rec.output_tokens, 80)
        self.assertEqual(rec.cache_read_tokens, 40)
        self.assertEqual(rec.cache_write_tokens, 0)
        self.assertEqual(rec.total_tokens, 220)
        self.assertEqual(rec.model, "glm-4.7-flash")

    def test_timestamp_milliseconds(self) -> None:
        rec = self._records()[0]
        self.assertEqual(rec.ts, 1793955262)  # 数据库存毫秒，统一按秒归一

    def test_workspace_and_session_attribution(self) -> None:
        rec = self._records()[0]
        self.assertEqual(rec.workspace, "TokenBoard")  # directory 取目录名
        self.assertEqual(rec.session_id, "ses_parent")  # 顶层会话用自身 session id

    def test_child_session_attributed_to_parent(self) -> None:
        records = self._records()
        child = records[1]
        self.assertEqual(child.session_id, "ses_parent")   # parent_id 归属父会话
        self.assertEqual(child.title, "顶层任务")          # 标题跟随父会话
        # reasoning 与 output 不相交：5 + 300；input: 500 + 900
        self.assertEqual(child.output_tokens, 305)
        self.assertEqual(child.input_tokens, 1400)
        self.assertEqual(child.model, "deepseek-v4.1")

    def test_dedup_key_is_message_id(self) -> None:
        for rec in self._records():
            self.assertTrue(rec.dedup_key.startswith("opencode:msg_"))

    def test_corrupt_db_raises_value_error(self) -> None:
        # 损坏文件必须叫 opencode.db 才会被发现（discover 只认该文件名 + 旧版 json/jsonl）
        sub = self.root / "broken"
        sub.mkdir()
        (sub / "opencode.db").write_bytes(b"not a sqlite file at all")
        broken = OpenCodeAdapter(roots=[str(sub)])
        files = broken.discover()
        self.assertEqual([f.name for f in files], ["opencode.db"])
        with self.assertRaises(ValueError):
            list(broken.iter_records(files[0]))

    def test_status_note_mentions_verified(self) -> None:
        status = self.adapter.status()
        self.assertTrue(status.verified)
        self.assertIn("不落盘", status.note)


class AgentApiTests(unittest.TestCase):
    '''agent_api 是给其它 agent 应用导入的接口；这里验证契约形状。'''

    def test_summarize_records_returns_summary(self) -> None:
        summary = usage_summary(platforms=["opencode"], since="7d")
        self.assertIn("kpi", summary)
        self.assertIn("sources", summary)
        self.assertIn("errors", summary)
        self.assertTrue(summary["window"]["label"])

        brief = report(platforms=["opencode"], since="7d")
        self.assertTrue(brief.strip())
        self.assertTrue(brief.startswith("##") or "usage" in brief or "简报" in brief
                        or "没有扫描到" in brief)

    def test_usage_record_dict_roundtrip(self) -> None:
        rec = UsageRecord(ts=1700000000, platform="opencode", workspace="w",
                          session_id="s", model="glm-4.7-flash", input_tokens=10,
                          output_tokens=5)
        self.assertEqual(summarize_records([rec]).total_tokens, 15)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""OpenCode 适配器（已用本机真实 V2 数据验证）。

OpenCode V2 把会话与请求级 usage 落在单个 SQLite 库（WAL 模式）：
``~/.local/share/opencode/opencode.db``。请求级 usage 在
``session_message.data``（``type='assistant'``，每次回复一行）：

    {"time":  {"created": <毫秒时间戳>, ...},
     "model": {"id": "...", "providerID": "...", "variant": "..."},
     "tokens": {"input": .., "output": .., "reasoning": ..,
                "cache": {"read": .., "write": ..}}}

``session_v2`` 提供 workspace（``directory``）、标题与 ``parent_id``
（task 子代理会话，应归属父会话统计，但各消息仍按会话内真实模型计价）。

口径（已用真实数据核对）：
  * ``tokens.input`` **不含**缓存读/写（Anthropic 风格，实测 18/41 条
    cache.read > input）；换算进 :class:`UsageRecord` 的**包含口径**：
    ``input_tokens = input + cache.read + cache.write``；
  * ``tokens.reasoning`` 与 ``tokens.output`` **不相交**（实测同一会话
    reasoning 之和 5396 > output 之和 4593）；reasoning 是真实产生的输出，
    因此 ``output_tokens = output + reasoning``，保证计价不漏思考 token；
  * ``session_v2.tokens_*`` 是增量累计的会话级快照，可能比消息明细略大
    （重试/流式更新不回减）；本适配器只信**请求级明细**，与 TokenBoard
    「每条请求一条记录」的契约一致。

安全与新鲜度：
  * 数据库**只读**打开；直接只读失败（WAL 的 -shm 不可用、被独占）时，
    把 db + -wal + -shm 拷到临时目录重开副本，绝不写原库；
  * **每次扫描都是重新扫描**：不落盘、不缓存、无本地数据库，聚合结果
    用完即弃。
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterator
from ..models import UsageRecord
from .base import BaseAdapter, parse_ts

DB_NAME = "opencode.db"
DB_SUFFIXES = (".db", ".sqlite", ".sqlite3")

_QUERY = """
SELECT m.id, m.data, s.id, s.directory, s.title, s.parent_id, p.title
FROM session_message m
JOIN session_v2 s ON s.id = m.session_id
LEFT JOIN session_v2 p ON p.id = s.parent_id
WHERE m.type = 'assistant'
ORDER BY m.time_created, m.id
"""


def _num(box: dict[str, Any], key: str) -> int:
    value = box.get(key)
    if value is None or isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class OpenCodeAdapter(BaseAdapter):
    name = "opencode"
    display_name = "OpenCode"
    root_globs = ("~/.config/opencode", "~/.local/share/opencode")
    file_suffixes = (".jsonl", ".json")
    verified = True
    auto_discover = True
    note = ("已验证真实 SQLite 会话库 opencode.db（V2），请求级 usage 含缓存与 reasoning；"
            "兼容旧版 json/jsonl；每次扫描现读现算，不落盘不缓存")

    # ------------------------------------------------------------------
    # 文件发现：SQLite 会话库 + 旧版 json/jsonl
    # ------------------------------------------------------------------
    def discover(self) -> list[Path]:
        files = set(super().discover())
        for root in self.roots():
            if root.is_dir():
                db = root / DB_NAME
                if db.is_file():
                    files.add(db)
        return sorted(files, key=str)

    def iter_records(self, path: Path, root: Path | None = None) -> Iterator[UsageRecord]:
        if path.suffix.lower() in DB_SUFFIXES:
            yield from self._iter_sqlite(path)
            return
        if path.suffix.lower() == ".json":
            yield from self.iter_json_document(path, self.make_context(path, root))
            return
        yield from super().iter_records(path, root)

    # ------------------------------------------------------------------
    # SQLite：只读直连，失败时临时副本兜底
    # ------------------------------------------------------------------
    def _conn_direct(self, path: Path) -> sqlite3.Connection | None:
        uri = path.resolve().as_uri() + "?mode=ro"
        try:
            return sqlite3.connect(uri, uri=True)
        except sqlite3.Error:
            return None

    def _load_rows(self, path: Path) -> list[tuple]:
        """只读直连失败（WAL shm 不可用 / 被独占 / 状态滞后）时，
        把 db + -wal + -shm 拷到临时目录重开副本，绝不写原库。"""
        conn = self._conn_direct(path)
        if conn is not None:
            try:
                return self._rows(conn, path)
            except sqlite3.Error:
                pass
            finally:
                conn.close()

        tmp_dir = tempfile.mkdtemp(prefix="tokenboard-opencode-")
        try:
            for suffix in ("", "-wal", "-shm"):
                src = Path(str(path) + suffix)
                try:
                    shutil.copy2(src, Path(tmp_dir) / (Path(path).name + suffix))
                except OSError:
                    pass  # wal/shm 缺失没关系：副本回放出主文件已有内容
            conn = sqlite3.connect(str(Path(tmp_dir) / path.name))
            try:
                return self._rows(conn, path)
            finally:
                conn.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _rows(self, conn: sqlite3.Connection, path: Path) -> list[tuple]:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"session_v2", "session_message"}.issubset(tables):
            raise ValueError(
                f"{path} 不是 OpenCode V2 会话库（缺 session_v2 / session_message 表，"
                "可能是 V1 目录；请改用 --path 扫描其 json/jsonl 日志）"
            )
        return list(conn.execute(_QUERY))

    def _iter_sqlite(self, path: Path) -> Iterator[UsageRecord]:
        try:
            rows = self._load_rows(path)
        except sqlite3.Error as exc:
            raise ValueError(f"无法读取 OpenCode 会话数据库 {path}: {exc}") from exc
        for message_id, raw, session_id, directory, title, parent_id, parent_title in rows:
            record = self._row_to_record(
                message_id, raw, session_id, directory, title, parent_id, parent_title
            )
            if record is not None:
                yield record

    # ------------------------------------------------------------------
    # 请求级解析 → UsageRecord（口径换算见模块 docstring）
    # ------------------------------------------------------------------
    def _row_to_record(
        self,
        message_id: Any,
        raw: Any,
        session_id: Any,
        directory: Any,
        title: Any,
        parent_id: Any,
        parent_title: Any,
    ) -> UsageRecord | None:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None

        tokens = data.get("tokens")
        if not isinstance(tokens, dict):
            return None
        inp = _num(tokens, "input")
        reasoning = _num(tokens, "reasoning")
        out = _num(tokens, "output")
        cache = tokens.get("cache")
        cache = cache if isinstance(cache, dict) else {}
        cache_read = _num(cache, "read")
        cache_write = _num(cache, "write")
        if not (inp or reasoning or out or cache_read or cache_write):
            return None  # 全零占位行不算请求

        time_box = data.get("time")
        ts = parse_ts(time_box.get("created")) if isinstance(time_box, dict) else None
        if ts is None:
            return None

        model_box = data.get("model")
        model = (
            str(model_box.get("id")).strip()
            if isinstance(model_box, dict) and str(model_box.get("id") or "").strip()
            else "unknown"
        )

        # OpenCode 口径（input 不含缓存）→ UsageRecord 口径（input 含缓存）
        workspace = Path(str(directory or "")).name or "opencode"
        return UsageRecord(
            ts=ts,
            platform=self.name,
            workspace=workspace,
            session_id=str(parent_id or session_id or "").strip(),
            model=model,
            title=(str(parent_title) if str(parent_title or "").strip() else str(title or "")),
            input_tokens=inp + cache_read + cache_write,
            output_tokens=out + reasoning,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            dedup_key=f"opencode:{message_id}",
        )

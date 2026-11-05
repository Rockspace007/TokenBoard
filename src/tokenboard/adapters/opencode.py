# -*- coding: utf-8 -*-
"""OpenCode 适配器（未用真实会话日志验证）。

OpenCode 的配置目录里可能既有 jsonl 也有整文件 JSON，两种形态都支持：
单文件 JSON 走 :meth:`BaseAdapter.iter_json_document`，jsonl 走逐行解析。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from ..models import UsageRecord
from .base import BaseAdapter


class OpenCodeAdapter(BaseAdapter):
    name = "opencode"
    display_name = "OpenCode"
    root_globs = ("~/.config/opencode", "~/.local/share/opencode")
    file_suffixes = (".jsonl", ".json")
    verified = False
    auto_discover = False
    note = "本机仅有配置文件、无会话日志；支持整文件 JSON 与 jsonl 两种形态"

    def iter_records(self, path: Path, root: Path | None = None) -> Iterator[UsageRecord]:
        if path.suffix.lower() == ".json":
            yield from self.iter_json_document(path, self.make_context(path, root))
            return
        yield from super().iter_records(path, root)

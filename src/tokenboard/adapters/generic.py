# -*- coding: utf-8 -*-
"""通用适配器：用户用 ``--path`` 指定任意文件或目录。

不做任何平台假设，只跑通用字段探测。适合新平台接入前的"能不能读出来"探路，
也适合把别人导出的 jsonl 直接喂进来看板。支持单文件、目录、jsonl、整文件 JSON。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from ..models import UsageRecord
from .base import BaseAdapter


class GenericAdapter(BaseAdapter):
    name = "generic"
    display_name = "自定义路径"
    root_globs = ()
    file_suffixes = (".jsonl", ".json")
    verified = False
    note = "通过 --path 指定任意目录或单文件；通用探测不保证覆盖私有字段"

    def discover(self) -> list[Path]:
        files: list[Path] = []
        for root in self.roots():
            if root.is_file():
                files.append(root)
            elif root.is_dir():
                for suffix in self.file_suffixes:
                    files.extend(root.rglob(f"*{suffix}"))
        return sorted({p for p in files if p.is_file()})

    def iter_records(self, path: Path, root: Path | None = None) -> Iterator[UsageRecord]:
        if path.suffix.lower() == ".json":
            yield from self.iter_json_document(path, self.make_context(path, root))
            return
        yield from super().iter_records(path, root)

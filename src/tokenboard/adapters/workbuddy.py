# -*- coding: utf-8 -*-
"""WorkBuddy 会话日志适配器。

这是**唯一用本机真实日志验证过**的适配器（29 个 jsonl，2026-11-05）。
日志形态：``~/.workbuddy/projects/<工作空间>/<sessionId>.jsonl``，
usage 在 ``providerData.rawUsage``（或 ``providerData.usage``）。
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..models import UsageRecord
from .base import BaseAdapter, ParseContext, extract_model, extract_ts, extract_usage, workspace_from

# 同一模型的不同别名合并，避免图例被拆成两条
MODEL_MERGE: dict[str, str] = {"glm-5.2-x": "glm-5.2"}


class WorkBuddyAdapter(BaseAdapter):
    name = "workbuddy"
    display_name = "WorkBuddy"
    root_globs = ("~/.workbuddy/projects",)
    verified = True
    note = "已用本机真实日志验证；providerData.rawUsage / usage；子代理日志归属父会话"

    def make_context(self, path: Path, root: Path | None = None) -> ParseContext:
        base = root or path.parent
        try:
            rel = path.relative_to(base)
        except ValueError:
            rel = Path(path.name)
        parts = rel.parts
        # 二级文件 = 会话文件；三级及更深（subagents/agent-*.jsonl）一律归属父会话，
        # 否则子代理会被算成独立会话，会话数与下钻层级都会失真。
        sid = Path(parts[1]).stem[:16] if len(parts) >= 2 else path.stem[:16]
        return replace(
            super().make_context(path, base),
            workspace=workspace_from(path, base),
            session_id=sid,
            title=_read_title(path),
        )

    def parse_line(self, obj: dict[str, Any], ctx: ParseContext) -> UsageRecord | None:
        usage = extract_usage(obj)
        ts = extract_ts(obj)
        if usage is None or ts is None:
            return None
        model = extract_model(obj)
        model = MODEL_MERGE.get(model, model)
        return UsageRecord(
            ts=ts,
            platform=self.name,
            workspace=ctx.workspace,
            session_id=ctx.session_id,
            model=model,
            title=ctx.title,
            **usage,
        )


def _read_title(path: Path) -> str:
    """读取会话日志里的 ``aiTitle``；没有就返回空串，由展示层回退到会话 ID。"""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                if '"aiTitle"' not in raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                title = obj.get("aiTitle") if isinstance(obj, dict) else None
                if isinstance(title, str) and title.strip():
                    return title.strip()
    except OSError:
        return ""
    return ""

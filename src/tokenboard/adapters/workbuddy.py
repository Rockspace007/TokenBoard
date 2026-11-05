# -*- coding: utf-8 -*-
"""WorkBuddy 会话日志适配器。

这是**唯一用本机真实日志验证过**的适配器（29 个 jsonl，2026-11-05）。
日志形态：``~/.workbuddy/projects/<工作空间>/<sessionId>.jsonl``，
usage 在 ``providerData.rawUsage``（或 ``providerData.usage``）。
"""
from __future__ import annotations

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
        return ParseContext(
            workspace=workspace_from(path, base),
            session_id=sid,
            path=str(path),
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
            **usage,
        )

# -*- coding: utf-8 -*-
"""OpenAI Codex CLI 适配器（未用真实数据验证）。

Codex 的 rollout 日志把 token 计数放在 ``token_count`` 事件里：
``{"type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{...}}}}``。
注意 ``total_token_usage`` 是**累计值**，逐行相加会重复计数，这里只取
``last_token_usage``（本次增量）。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..models import UsageRecord
from .base import BaseAdapter, ParseContext, extract_model


class CodexAdapter(BaseAdapter):
    name = "codex"
    display_name = "OpenAI Codex CLI"
    root_globs = ("~/.codex/sessions", "~/.codex/history")
    verified = False
    auto_discover = False
    note = "本机未安装；支持 rollout 的 token_count 增量事件，累计值已排除"

    def parse_line(self, obj: dict[str, Any], ctx: ParseContext) -> UsageRecord | None:
        # 先走通用探测，兼容把 usage 平铺在顶层的变体
        record = super().parse_line(obj, ctx)
        if record is not None:
            return record

        payload = obj.get("payload")
        if not isinstance(payload, dict):
            return None
        info = payload.get("info")
        if not isinstance(info, dict):
            return None
        usage = info.get("last_token_usage")
        if not isinstance(usage, dict) or not usage:
            return None

        # 把增量 usage 伪装成顶层 usage，复用同一套字段探测与 clamp 逻辑
        probe = dict(obj)
        probe["usage"] = usage
        record = super().parse_line(probe, ctx)
        if record is None:
            return None
        model = extract_model(obj, record.model)
        model = extract_model(payload, model)
        return replace(record, model=model)

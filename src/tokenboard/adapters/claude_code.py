# -*- coding: utf-8 -*-
"""Claude Code 会话日志适配器（未用真实数据验证）。

公开日志形态：``~/.claude/projects/<slug>/<sessionId>.jsonl``，
每行含 ``message.usage.{input_tokens,output_tokens,cache_read_input_tokens,
cache_creation_input_tokens}`` 与 ``message.model``、``timestamp``、``sessionId``。
这些路径都已在 :mod:`tokenboard.adapters.base` 的通用探测表中，故无需覆盖解析。
"""
from __future__ import annotations

from .base import BaseAdapter


class ClaudeCodeAdapter(BaseAdapter):
    name = "claude_code"
    display_name = "Claude Code"
    root_globs = ("~/.claude/projects", "~/.config/claude/projects")
    verified = False
    auto_discover = False
    note = "本机未安装；按公开 jsonl 字段实现。请用 --path 指向真实目录验证后把 verified 改为 True"

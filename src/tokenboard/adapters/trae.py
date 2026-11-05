# -*- coding: utf-8 -*-
"""Trae / TraeCode 适配器（路径与格式均未验证）。

Trae 的会话日志目录在不同版本/不同发行版之间不一致，这里只列出常见候选
路径并**明确标注未验证**。真正的适配步骤见 ``docs/ADAPTERS.md``：
  1. 用 ``--path`` 指向真实日志目录；
  2. 跑 ``tokenboard probe --path ...`` 看字段命中率；
  3. 补平台特有字段后把 ``verified`` 改为 True 并补 fixture。
"""
from __future__ import annotations

from .base import BaseAdapter


class TraeAdapter(BaseAdapter):
    name = "trae"
    display_name = "Trae / TraeCode"
    root_globs = (
        "~/.trae",
        "~/.trae-cn",
        "~/.config/Trae",
        "~/Library/Application Support/Trae",
    )
    verified = False
    auto_discover = False
    note = (
        "本机 ~/.trae-cn 下只有 memory/projects/**/session_memory_*.jsonl（会话记忆，无 usage 字段），"
        "不是用量日志；真实日志路径待确认，请用 --path 指定并补 fixture"
    )

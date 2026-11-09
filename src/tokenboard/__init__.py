# -*- coding: utf-8 -*-
"""TokenBoard — 多平台 LLM Token 消耗看板。

零第三方依赖，Python 3.10+。统一把各平台会话日志归一为 UsageRecord，
再做聚合、计价与单文件离线 HTML 渲染。

三个入口（共用本包同一套代码）：
  1) CLI：``python -m tokenboard ...`` / ``tokenboard serve``
  2) MCP：``python -m tokenboard serve-mcp``
  3) Skill 版：见仓库根目录 ``SKILL.md``
"""
__version__ = "0.6.2"

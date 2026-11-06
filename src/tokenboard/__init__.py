# -*- coding: utf-8 -*-
"""TokenBoard — 多平台 LLM Token 消耗看板。

零第三方依赖，Python 3.9+。统一把各平台会话日志归一为 UsageRecord，
再做聚合、计价与单文件离线 HTML 渲染。

两种使用形态：
  1) agent tool：``python -m tokenboard ...`` / ``python -m tokenboard serve-mcp``
  2) WorkBuddy skill：见仓库根目录 ``skill/SKILL.md``
"""
__version__ = "0.4.0"

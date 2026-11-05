#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy Skill 入口（薄壳）。

与 agent tool 版共享 ``src/tokenboard`` 里的同一套核心代码，不复制、不 fork，
因此 CLI / MCP / Skill 三个入口的统计口径永远一致。

安装后目录形态（整个仓库 clone 到用户级技能目录即可）：
    ~/.workbuddy/skills/tokenboard/
      ├── SKILL.md
      ├── scripts/gen_dashboard.py   <- 本文件
      └── src/tokenboard/            <- 核心包
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if not (SRC / "tokenboard" / "__init__.py").is_file():
    sys.stderr.write(
        "[tokenboard] 找不到核心包 src/tokenboard。\n"
        "请把整个仓库 clone 到技能目录，而不是只复制 SKILL.md：\n"
        "  git clone <repo> ~/.workbuddy/skills/tokenboard\n"
    )
    raise SystemExit(2)

# 允许在未 pip install 的情况下直接运行
sys.path.insert(0, str(SRC))

from tokenboard.cli import main  # noqa: E402  (必须在 sys.path 调整之后导入)

if __name__ == "__main__":
    raise SystemExit(main())

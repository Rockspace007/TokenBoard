#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端 MCP 自检：启动 serve-mcp 子进程，发四帧，校验响应契约。

    python scripts/smoke_mcp.py

不发真实网络请求、不写用户数据，可直接放进 CI。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))

FRAMES = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},          # 不应有回复
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "tokenboard_platforms", "arguments": {}}},
]


def main() -> int:
    payload = "".join(json.dumps(frame, ensure_ascii=False) + "\n" for frame in FRAMES)
    proc = subprocess.run(
        [sys.executable, "-m", "tokenboard", "serve-mcp"],
        input=payload, capture_output=True, text=True, env=ENV, timeout=30,
    )
    lines = [json.loads(x) for x in proc.stdout.strip().splitlines() if x.strip()]
    if len(lines) != 3:
        raise SystemExit(
            f"期望 3 帧响应（notification 不回复），实得 {len(lines)}\n"
            f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    assert lines[0]["id"] == 1 and "serverInfo" in lines[0]["result"], lines[0]
    assert len(lines[1]["result"]["tools"]) == 4, lines[1]
    assert lines[2]["result"]["isError"] is False, lines[2]
    assert "workbuddy" in lines[2]["result"]["content"][0]["text"], lines[2]
    print("MCP smoke OK: initialize / notification / tools/list / tools/call")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

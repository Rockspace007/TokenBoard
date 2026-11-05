#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Skill 版打成一个自包含 tgz（只含 SKILL.md + scripts + src）。

用途：不想 clone 整个仓库时，直接把这个包解压到
``~/.workbuddy/skills/tokenboard/`` 即可使用。

    python scripts/pack_skill.py                 # 输出 dist/tokenboard-skill.tgz
    python scripts/pack_skill.py --out ~/Desktop/tb.tgz
"""
from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _exclude(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = info.name
    if "__pycache__" in name or name.endswith((".pyc", ".pyo", ".DS_Store")):
        return None
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description="打包 TokenBoard Skill 最小分发版")
    parser.add_argument("--out", default=str(ROOT / "dist" / "tokenboard-skill.tgz"))
    args = parser.parse_args()
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    members = [
        (ROOT / "SKILL.md", "tokenboard/SKILL.md"),
        (ROOT / "scripts" / "gen_dashboard.py", "tokenboard/scripts/gen_dashboard.py"),
        (ROOT / "src" / "tokenboard", "tokenboard/src/tokenboard"),
    ]
    for source, _ in members:
        if not source.exists():
            raise SystemExit(f"缺少文件：{source}")

    with tarfile.open(out, "w:gz") as tar:
        for source, arcname in members:
            tar.add(source, arcname=arcname, filter=_exclude)
    print(f"已打包 {out}  ({out.stat().st_size / 1024:.1f} KB)")
    print("安装：mkdir -p ~/.workbuddy/skills/tokenboard && tar -xzf <tgz> -C ~/.workbuddy/skills --strip-components=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

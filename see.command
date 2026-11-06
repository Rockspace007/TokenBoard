#!/usr/bin/env sh
# TokenBoard 一键入口（macOS 双击 .command / 终端均可）
#
# 双击或运行本文件：重新扫描全部已验证平台 → 生成 tokenboard.html →
# 自动用默认浏览器打开看板。
#
# 用法：
#   · 双击（默认近 30 天、全部平台）
#   · 终端带参数：./see.command --since 7d
#
# 数据安全：每次运行都是**重新统计**（不落盘、无本地累计库）；唯一产物
# tokenboard.html 已被 .gitignore 排除，绝不带上本机数据提交到 GitHub。
#
# 首次运行如被系统拦截：右键 → 打开；或终端执行 chmod +x see.command
set -eu
cd "$(dirname "$0")"

# 选 Python：优先仓库自带虚拟环境，其次 python3（Windows 下为 python）
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    PYTHON="python"
fi

PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" exec "$PYTHON" -m tokenboard scan --open "$@"

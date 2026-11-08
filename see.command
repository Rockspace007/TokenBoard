#!/usr/bin/env sh
# TokenBoard 一键入口（macOS 双击 .command / 终端均可）
#
# 双击或运行本文件：启动「实时看板」本地服务，并自动在默认浏览器打开。
# 实时模式下，页面右上角的「刷新」按钮会重新扫描本机最新日志，
# 无需退出重启即可看到最新 Token 消耗。
#
# 用法：
#   · 双击（默认近 30 天、全部平台、浅色主题 → http://127.0.0.1:8000/）
#   · 终端带参数：./see.command --port 9000 --theme dark --since 7d
#
# 停止服务：关闭本终端窗口，或在窗口内按 Ctrl+C。
#
# 数据安全：每次刷新都是**重新统计**（不落盘、无本地累计库）；本机数据
# 绝不提交到 GitHub（仓库内 tokenboard.html 已被 .gitignore 排除）。
#
# 兼容旧行为：加 --static 改为「生成静态文件」模式（生成 tokenboard.html 并打开，
# 该模式下页面「刷新」按钮仅重载当前快照，不会回读本机日志）。
#
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

PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

# 旧「静态文件」模式：--static 走 scan --open
if [ "${1:-}" = "--static" ]; then
    shift
    exec "$PYTHON" -m tokenboard scan --open "$@"
fi

echo "▶ TokenBoard 实时看板启动中… 浏览器将自动打开 http://127.0.0.1:8000/"
echo "▶ 停止服务：关闭此窗口 或 按 Ctrl+C"
exec "$PYTHON" -m tokenboard serve --open "$@"

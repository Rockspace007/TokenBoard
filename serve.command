#!/usr/bin/env sh
# TokenBoard · 版本 A：本地服务版（可刷新）
#
# 双击本文件（或终端运行）：启动本地 HTTP 服务并自动在浏览器打开看板。
# 页面右上角「刷新」按钮会重新扫描本机日志、拉取最新 Token 消耗，
# 不需要退出重启。数据源表里的「导入」按钮也只有在这个版本里能真扫描。
#
# 查看地址：http://127.0.0.1:8000/ （默认端口，可用 --port 改）
# 停止服务：关闭这个终端窗口，或在窗口内按 Ctrl+C。
#
# 常用参数（终端运行时透传给 tokenboard serve）：
#   ./serve.command --port 9000
#   ./serve.command --since 7d --theme dark
#   ./serve.command --platform workbuddy
#
# 只监听 127.0.0.1，日志数据不出本机；每次请求都是重新统计、不落盘。
# 本版本不产出 HTML 文件——页面由服务端现场生成。
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

export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

# 从参数里读出端口，让启动提示准确（支持 --port 9000 与 --port=9000）
PORT=8000
_prev=""
for _arg in "$@"; do
    case "$_prev" in --port) PORT="$_arg" ;; esac
    case "$_arg" in --port=*) PORT="${_arg#--port=}" ;; esac
    _prev="$_arg"
done

echo "▶ TokenBoard 本地服务版启动中… 浏览器将自动打开 http://127.0.0.1:${PORT}/"
echo "▶ 页面点「刷新」即重新扫描本机日志；停止：关闭此窗口 或 按 Ctrl+C"
exec "$PYTHON" -m tokenboard serve --open "$@"

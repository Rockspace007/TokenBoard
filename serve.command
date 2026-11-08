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

# 仓库绝对路径，保证 PYTHONPATH 与 Python 选择都不依赖当前工作目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

# 选 Python：要求 >= 3.10 且能成功 import tokenboard（按优先级尝试）
PYTHON=""
candidates="$SCRIPT_DIR/.venv/bin/python"
for p in "$HOME"/.workbuddy/binaries/python/versions/*/bin/python3; do
  [ -x "$p" ] && candidates="$candidates $p"
done
candidates="$candidates python3 python /opt/homebrew/bin/python3 /usr/local/bin/python3"

for cand in $candidates; do
  [ -x "$cand" ] || continue
  ok=$("$cand" -c 'import sys;print(1 if sys.version_info>=(3,10) else 0)' 2>/dev/null)
  [ "$ok" = "1" ] || continue
  if "$cand" -c 'import tokenboard' >/dev/null 2>&1; then
    PYTHON="$cand"; break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "❌ 未找到可用的 Python（需要 >= 3.10 且能导入 tokenboard）。"
  echo "   可尝试：先 cd 到本仓库目录，再运行  python3 -m tokenboard serve"
  echo "   或安装：pip install -e ."
  echo "   按回车关闭此窗口…"
  read -r _
  exit 1
fi

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
"$PYTHON" -m tokenboard serve --open "$@"
rc=$?
if [ $rc -ne 0 ]; then
  echo "❌ 服务启动失败（退出码 $rc）。常见原因：端口 ${PORT} 已被占用。"
  echo "   换端口重试：./serve.command --port 9000"
  echo "   按回车关闭此窗口…"
  read -r _
fi
exit $rc

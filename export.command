#!/usr/bin/env sh
# TokenBoard · 版本 B：静态导出版（双击即出 HTML）
#
# 双击本文件（或终端运行）：扫描本机日志 → 生成单文件离线 HTML → 自动用浏览器打开。
# 产物默认就是仓库根目录的 tokenboard.html，可以用 --out 换成任意路径。
# 这个文件是完全自包含的：无 CDN、无网络请求，可以直接发给别人或归档。
#
# 注意：这是「生成那一刻的快照」。页面右上角「刷新」只重载当前这份文件，
# 不会回读本机新日志；数据源表的「导入」按钮也会提示改用 serve.command。
# 想要点刷新就更新数据，请用版本 A（./serve.command）。
#
# 常用参数（终端运行时透传给 tokenboard scan）：
#   ./export.command --out ~/Desktop/看板.html
#   ./export.command --since 7d --theme dark
#   ./export.command --platform workbuddy
#
# 生成的 HTML 含请求级明细，对外分享前请确认（详见 README「隐私与免责」）。
# 仓库内的 tokenboard.html 已被 .gitignore 排除，不会被提交到 GitHub。

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
  echo "   可尝试：先 cd 到本仓库目录，再运行  python3 -m tokenboard scan"
  echo "   或安装：pip install -e ."
  echo "   按回车关闭此窗口…"
  read -r _
  exit 1
fi

# 从参数里读出输出路径，让提示准确（支持 --out XXX 与 --out=XXX）
OUT="tokenboard.html"
_prev=""
for _arg in "$@"; do
  case "$_prev" in --out) OUT="$_arg" ;; esac
  case "$_arg" in --out=*) OUT="${_arg#--out=}" ;; esac
  _prev="$_arg"
done

echo "▶ TokenBoard 静态导出版：正在扫描本机日志…"
echo "▶ 产物：${OUT}（生成后自动打开浏览器）"
echo "▶ 提示：这是快照，点页面「刷新」不会读新日志；要实时刷新请用 ./serve.command"
"$PYTHON" -m tokenboard scan --open "$@"
rc=$?
if [ $rc -ne 0 ]; then
  echo "❌ 导出失败（退出码 $rc）。"
  echo "   按回车关闭此窗口…"
  read -r _
fi
exit $rc

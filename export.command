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
exec "$PYTHON" -m tokenboard scan --open "$@"

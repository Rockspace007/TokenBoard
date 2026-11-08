#!/usr/bin/env sh
# TokenBoard · 兼容入口（旧名称，保留以免打断已有双击习惯）
#
# 项目现在有两个语义明确的版本，请优先直接用它们：
#   ./serve.command    版本 A · 本地服务版（点「刷新」更新数据）
#   ./export.command   版本 B · 静态导出版（双击生成单文件 HTML）
#
# 本文件等价于：
#   ./see.command              → ./serve.command
#   ./see.command --static …   → ./export.command …
#
set -eu
cd "$(dirname "$0")"

if [ "${1:-}" = "--static" ]; then
    shift
    exec ./export.command "$@"
fi
exec ./serve.command "$@"

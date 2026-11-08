# 给其它 agent 应用的导入接口

TokenBoard 是「数据不出本机」的零依赖工具，其它任何 agent（OpenCode、Claude Code、
Codex、Trae、Cursor、Cline、WorkBuddy…）都可以用下面的方式把消耗统计接进去。
**四种方式共用同一套 `scan → summarize` 代码，口径完全一致。**

核心承诺：

- **每次统计都是重新统计**：现读平台日志源头 → 聚合 → 返回，不落盘、无本地累计
  数据库、无跨次缓存；
- 只读 usage、时间戳、模型名、会话 ID、工作空间目录名，**不读消息正文**；
- 生成的看板/导出不会进 git（`.gitignore` 已排除 `tokenboard.html` / `dist/` /
  `data/` / `*.db` 等）。

## 方式一 · Python 直接 import（最省事）

```python
from tokenboard.agent_api import (
    usage_records,     # 请求级明细：list[dict]
    usage_summary,     # 聚合结果：KPI / 模型 / 平台 / 会话 / 日趋势（dict）
    report,            # 中文 Markdown 简报，可直接放进对话或通知
    render_board,      # 生成单文件离线 HTML 看板
    platforms,         # 各平台数据源状态
)

# 你的 agent 工具函数里：
print(report(since="7d"))                       # 口头汇报用
kpi = usage_summary(platforms=None, since="7d")["kpi"]   # 自己加工用
records = usage_records(paths=["~/某平台日志"])  # 任意 jsonl 目录也可以

board = render_board(since="30d", out="tokenboard.html", open_browser=True)
# → {"path": ".../tokenboard.html", "records": 71, "kpi": {...}, ...}
```

`since` / `until` 支持 Unix 秒、`7d` 相对天数与 `YYYY-MM-DD`，与 CLI 同一解析。

## 方式二 · CLI 结构化输出（任何能跑 shell 的 agent）

```bash
tokenboard scan --since 7d --format json        # 稳定 JSON（含 sources/errors）
tokenboard scan --format table                  # 纯文本表格，便宜可靠
tokenboard platforms                            # 看本机有哪些平台数据源
```

Agent 只需要约定一个规则：优先读 json 的 `kpi` 字段，出错时读 `errors`。

## 方式三 · MCP Server（给支持 MCP 的 agent）

零依赖 stdio JSON-RPC（详见 `docs/CONTRACT.md`），四个工具：
`tokenboard_scan` / `tokenboard_render` / `tokenboard_platforms` / `tokenboard_brands`。

按 agent 配置文件粘贴（`PYTHONPATH` 换成你的仓库绝对路径；pip 安装过可去掉）：

**OpenCode**（`~/.config/opencode/opencode.json`）：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "tokenboard": {
      "type": "local",
      "command": ["python3", "-m", "tokenboard", "serve-mcp"],
      "environment": { "PYTHONPATH": "/Users/you/path/TokenBoard/src" }
    }
  }
}
```

**Claude Code / 通用 `mcpServers`**（`~/.claude.json`、Cursor `~/.cursor/mcp.json`、
Cline、Trae 等同构配置）：

```json
{
  "mcpServers": {
    "tokenboard": {
      "command": "python3",
      "args": ["-m", "tokenboard", "serve-mcp"],
      "env": { "PYTHONPATH": "/Users/you/path/TokenBoard/src" }
    }
  }
}
```

Claude Code 也可以一条命令注册：

```bash
claude mcp add tokenboard -- \
  env PYTHONPATH=/Users/you/path/TokenBoard/src python3 -m tokenboard serve-mcp
```

验证：`python scripts/smoke_mcp.py`（握手 + tools/list + tools/call 端到端）。

## 方式四 · 包成 Skill / 系统入口

- 本仓库整体就是一个 WorkBuddy Skill（`SKILL.md`），安装方式见 README「版本 C · WorkBuddy Skill」；
  也可用 `python scripts/pack_skill.py` 打出可直接导入的 `dist/tokenboard-skill.tgz`。
- 给 macOS/本地用户做入口可照仓库根目录两个脚本的思路：
  `export.command` → `python3 -m tokenboard scan --open`（生成静态 HTML + 浏览器直开），
  `serve.command` → `python3 -m tokenboard serve --open`（本地服务 + 页面点「刷新」重扫日志），
  或结合本仓库 `agent_api.render_board(open_browser=True)`。
  安装方式及各版本差异见 README「快速开始」。

## Windows 注意

`PYTHONPATH=src` 换成 `set PYTHONPATH=src`（cmd）或 `$env:PYTHONPATH="src"`
（PowerShell）；其余命令一致。所有平台适配都只依赖 Python 3.10+ 标准库。

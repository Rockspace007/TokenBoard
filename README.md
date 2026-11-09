# TokenBoard

> 多平台 LLM Token 消耗看板 · 请求级明细 · 单文件离线 HTML · 零第三方依赖 · 数据不出本机

把 WorkBuddy、Claude Code、Codex、Trae、OpenCode 等工具写在本机磁盘上的会话日志，
统一成一张可交互的消耗看板：先看「花了多少、命中多少、花在哪」，再逐级下钻到每一次请求。
Python 3.10+ 标准库即可运行，不装包、不联网；既可以在本地服务里点「刷新」随时更新，
也可以导出一个单文件 HTML 直接分发，或装成 Skill 在对话里一句话生成。

![python](https://img.shields.io/badge/python-3.10%2B-blue)
![deps](https://img.shields.io/badge/dependencies-0-brightgreen)
![tests](https://img.shields.io/badge/tests-103%20passing-brightgreen)
![license](https://img.shields.io/badge/license-MIT-green)

**目录**：[主要功能](#主要功能) · [安装](#安装) · [快速开始](#快速开始) · [常用命令与参数](#常用命令与参数) · [支持的平台](#支持的平台) · [文档](#文档) · [开发](#开发) · [隐私与免责](#隐私与免责) · [License](#license)

## 主要功能

- **多平台统一口径**：一个 `UsageRecord` 契约吃下 6 类日志来源，归一化为时间 / 平台 / 工作空间 / 会话 / 模型 / 输入输出 / 缓存读写 / 总量，并按每条请求的实际缓存命中估算金额。新增平台只需写一个 adapter。
- **结论优先的看板**：KPI 行一次给出合计 Token、请求次数、预估金额、缓存命中率、日均、会话数、输入输出比；下面依次是模型构成、数据源状态、使用分布与时间节律。
- **页内真交互**：周期胶囊（`1 天` 默认 / `2 天` / `3 天` / `近 7 天` / `近 30 天` / `总量`）、自定义日期区间、**指定日日历**都按同一口径重新聚合；工作空间 → 会话 → 请求三级下钻、模型点选聚焦、跟随式悬浮明细、双主题切换并记忆偏好。
- **完整时间维度**：0—24 时分布（累计 / 仅当日页内可切，曲线数量 TOP 3 / 5 / 10 / 全部可切）、单次请求大小分布（p50 / p90）、日活日 / 周 / 月热力；工作空间 / 会话榜每行附带行内热力分布，粒度可切「日 · 当日 24 时 / 周 · 当周 7 天 / 月 · 当月」。顶部 KPI 跟随周期胶囊（近 N 天 / 总量）重算；下方工作空间榜、会话榜、分布热力图、日活分布、单次请求大小分布等明细卡统一按全部数据的总量口径展示，不受周期切换影响，便于跨周期稳定对比。
- **三种使用形态**：本地服务版（点「刷新」重扫日志）、静态导出版（单文件离线 HTML）、Skill 版（在 Agent 对话里生成），三者共用同一套扫描与计价代码，数字口径完全一致。
- **诚实的数据源状态**：数据源表按本机是否真有日志显示「已验证 / 未验证」与「✓ 已导入 / 未导入」；点「导入」会真扫一遍该平台，0 条记录时明确提示，绝不假装成功。**不需要在对应平台里接入任何 Skill 或插件**（见下文「导入按钮」小节）。
- **隐私与零依赖**：运行期只用 Python 标准库，静态 HTML 无 CDN、无外部字体、不发网络请求；服务版只监听 `127.0.0.1`；只读取 usage、时间戳、模型名、会话 ID、工作空间目录名，不读取也不输出消息正文；不落盘累计库，每次统计都重新扫描。
- **多种出口**：CLI 可输出 `html` / `json` / `table`，另有 Python API、MCP Server（4 个工具）与外部 CSV / JSON 用量文件导入，方便脚本与 Agent 集成。

浅色（白底荧光绿）为默认主题，深色「暗夜玻璃」页内一键切换。绿色系只用于 UI 框架，
模型厂商品牌色只用于数据系列且永远附文字标签，全表见 [`docs/DESIGN_TOKENS.md`](docs/DESIGN_TOKENS.md)。

## 安装

### 环境要求

Python **3.10+**（3.10 / 3.11 / 3.12 / 3.13 均在 CI 覆盖范围内），无需 `pip install` 任何运行期依赖，
macOS / Linux / Windows 均可。三种安装方式任选其一，功能完全一致。

### 方式 1 · 克隆仓库（推荐）

```bash
git clone https://github.com/Rockspace007/TokenBoard.git
cd TokenBoard
```

仓库自带 macOS 一键脚本，双击即可运行（首次被系统拦截就右键 → 打开）：

| 脚本 | 作用 |
|---|---|
| `serve.command` | 启动本地服务版，自动打开浏览器 |
| `export.command` | 扫描日志并导出 `tokenboard.html`，自动打开 |

> 旧版 `see.command` 已移除，请直接双击 `serve.command`。

不用脚本、或在 Windows / Linux 上，直接设置 `PYTHONPATH` 运行即可：

```bash
PYTHONPATH=src python3 -m tokenboard serve --open    # macOS / Linux
$env:PYTHONPATH="src"; python -m tokenboard serve --open   # Windows PowerShell
```

### 方式 2 · pip 安装（命令行全局可用）

```bash
pip install git+https://github.com/Rockspace007/TokenBoard.git
tokenboard --version        # 验证安装
```

安装后无需仓库目录，任意位置都能用 `tokenboard scan` / `tokenboard serve` 等子命令。

### 方式 3 · Skill 版（导入 Agent 技能目录）

把 TokenBoard 装成 Skill 后，在对话里说「看看我的 token 用量」即可生成看板，不用记命令。
下面以 WorkBuddy 的技能目录 `~/.workbuddy/skills` 为例，其它使用同类 Skill 目录的 Agent 换成对应路径即可。

```bash
mkdir -p ~/.workbuddy/skills

# 从 GitHub Releases 下载 tokenboard-skill.tgz 后解压（推荐，免克隆）
tar -xzf tokenboard-skill.tgz -C ~/.workbuddy/skills

# 或：在克隆后的仓库里自行打包
python3 scripts/pack_skill.py            # → dist/tokenboard-skill.tgz
tar -xzf dist/tokenboard-skill.tgz -C ~/.workbuddy/skills
```

包内条目自带 `tokenboard/` 前缀，**不要加 `--strip-components`**。解压后应为：

```
~/.workbuddy/skills/tokenboard/
  ├── SKILL.md
  ├── scripts/gen_dashboard.py
  └── src/tokenboard/
```

也可以直接把整个仓库克隆到技能目录：

```bash
git clone https://github.com/Rockspace007/TokenBoard.git ~/.workbuddy/skills/tokenboard
```

重启 Agent 会话后即可触发。安装不完整的典型症状是找不到 `src/tokenboard/__init__.py`——只复制 `SKILL.md` 会导致这个错误。
Skill 版产出的是**静态 HTML**（同版本 B），不会启动服务。

### 可选 · 作为 MCP Server 接入其它 Agent

```json
{
  "mcpServers": {
    "tokenboard": {
      "command": "python3",
      "args": ["-m", "tokenboard", "serve-mcp"],
      "env": { "PYTHONPATH": "/absolute/path/to/TokenBoard/src" }
    }
  }
}
```

stdio JSON-RPC，不监听端口，暴露 `tokenboard_scan` / `tokenboard_render` /
`tokenboard_platforms` / `tokenboard_brands` 四个工具。协议见 [`docs/CONTRACT.md`](docs/CONTRACT.md)。

## 快速开始

三个版本**共用同一套扫描、归一化与计价代码**，区别只在「怎么看」和「数据何时更新」：

| | **A · 本地服务版** | **B · 静态导出版** | **C · Skill 版** |
|---|---|---|---|
| 一句话 | 常驻服务，点「刷新」就更新 | 双击导出一个 HTML 文件 | 在对话里说一句话生成看板 |
| 适合谁 | 每天看、边用边刷新 | 归档 / 发给别人 / 离线查看 | 不想开终端，让 Agent 帮你查 |
| 入口 | `./serve.command` | `./export.command` | 已导入的 Skill |
| 产物 | 不产出文件，页面现场生成 | `tokenboard.html`（单文件离线） | Agent 生成的 HTML |
| 在哪看 | `http://127.0.0.1:8000/` | 双击该 HTML，任意浏览器 | Agent 内直接打开 |
| 数据怎么更新 | 页面「刷新」重新扫描本机日志 | 重新运行脚本覆盖文件 | 重新发起一轮对话 |
| 「导入」按钮 | 真扫描、真并入 | 提示改用 A 版 | 提示改用 A 版 |

> 自己天天看 → **A**；要一个能发出去的文件 → **B**；想在对话里问 → **C**。

### A · 本地服务版（可刷新）

```bash
./serve.command                          # macOS 双击，默认 8000 端口并自动开浏览器
./serve.command --port 9000              # 换端口
./serve.command --since 7d --theme dark  # 每次刷新都按近 7 天口径重扫

tokenboard serve --open                  # 已 pip 安装，任意系统
```

浏览器打开 `http://127.0.0.1:8000/`。点右上角「**刷新**」即重新扫描本机日志、重新渲染整页，
不用退出重启；按 `Ctrl+C` 或关掉终端窗口即停止。不带 `--since` 时扫描仍是全历史，
页面默认聚焦「1 天」，可随时切到近 30 天或「总量」，不会丢数据。

### B · 静态导出版（直接运行就出 HTML）

```bash
./export.command                                  # → ./tokenboard.html，自动打开
./export.command --out ~/Desktop/看板-1108.html   # 自定义产物路径
./export.command --since 30d --theme dark         # 导出近 30 天 / 深色

tokenboard scan --open                            # 已 pip 安装
tokenboard scan --since 7d --out week.html
```

生成的 HTML 完全自包含：断网、拷到 U 盘、发给同事都能看，页内交互全部保留。
页面「刷新」**只重载这份快照**，不会回读新日志；「导入」按钮会提示改用 A 版。
仓库内的 `tokenboard.html` 已被 `.gitignore` 排除，不会提交到 GitHub。

### C · Skill 版

按上文「方式 3」安装后，重启 Agent 会话，直接说：

> 「看看我的 token 用量」/「生成本周消耗看板」/「对比各平台用量」/「token 审计」

Agent 会通过 `scripts/gen_dashboard.py` 调用同一套核心代码生成静态 HTML 并汇报关键数字。

### 关于「导入」按钮

**不需要在对应平台里接入任何 Skill 或插件。** TokenBoard 读的是各软件自己写在本机磁盘上的会话日志：

| 平台 | 默认读取位置 |
|---|---|
| WorkBuddy | `~/.workbuddy/projects` |
| Claude Code | `~/.claude/projects`、`~/.config/claude/projects` |
| OpenAI Codex CLI | `~/.codex/sessions`、`~/.codex/history` |
| Trae / TraeCode | `~/.trae-cn/hub_event_cache` |
| OpenCode | `~/.config/opencode`、`~/.local/share/opencode` |

点「导入」＝让服务端直接读这个目录，并把该平台纳入本次服务的统计范围；不连平台账号、
不需要平台侧配合，也不是给平台装东西。能不能拿到数据只取决于「本机装没装、有没有产生可读日志」：
文件数为 0 时页面会提示「本机未安装或暂无日志，未导入数据」。
`auto_discover=False` 的平台（Claude Code / Codex / Trae）默认不参与自动扫描，导入按钮正是按需把它们接进统计。
导入集合只存本次服务进程内存、不落盘，重启服务后需重新点导入。

> Skill 版是 TokenBoard 自己被安装成技能的方式，决定的是「怎么发起查看」，不是「数据从哪来」。

## 常用命令与参数

```bash
tokenboard scan                         # 生成 ./tokenboard.html（默认子命令）
tokenboard serve --open                 # 本地实时看板
tokenboard platforms                    # 看本机有哪些平台日志
tokenboard scan --format json           # 结构化输出，给脚本 / Agent 用
tokenboard probe --path ~/some/logs     # 新平台接入前先看字段命中率
tokenboard import usage.csv --platform trae --format table
```

`import` 支持 `--map FIELD=SOURCE`（可重复，如 `--map ts=created_at --map input_tokens=prompt_tokens`）
与 `--records data.items`（指定 JSON 中记录数组的点分路径）；Trae 用量页抓取见
[`scripts/README-trae-capture.md`](scripts/README-trae-capture.md)。

子命令：`scan`（默认）、`serve`、`import`、`platforms`、`brands`、`probe`、`serve-mcp`。

| 参数 | 说明 |
|---|---|
| `--platform` | 只扫指定平台，可重复 |
| `--path` | 自定义日志目录/文件；给定后忽略 `--platform` |
| `--since 7d` / `--until 2026-11-05` | 时间窗，支持 `YYYY-MM-DD` 与 `Nd`；页面内仍可切换周期 |
| `--out` | 输出路径，HTML 默认 `tokenboard.html` |
| `--open` | `scan` 写完 HTML / `serve` 起服务后自动打开浏览器 |
| `--format html\|json\|table` | 输出形态 |
| `--theme dark\|light` | 默认 light，页面内也可切换 |
| `--prices <json>` | 覆盖牌价，如 `{"glm":[2,8,0.4]}` |
| `--title` | 自定义标题 |
| `--host` / `--port` | 仅 `serve`，默认 `127.0.0.1:8000` |

## 支持的平台

| 平台 | 参数 | 本机验证 | 说明 |
|---|---|---|---|
| WorkBuddy | `--platform workbuddy` | ✅ 已用真实日志验证 | `providerData.rawUsage`；子代理归属父会话 |
| Claude Code | `--platform claude_code` | ❌ 未验证 | `message.usage.*` |
| OpenAI Codex CLI | `--platform codex` | ❌ 未验证 | `token_count` 增量事件；已排除累计值 |
| Trae / TraeCode | `--platform trae` | ⚠️ 部分验证 | 仅 `hub_event_cache` 的 `token_usage` 明文可读；其余历史在加密 `database.db` |
| OpenCode | `--platform opencode` | ✅ 已用真实日志验证 | V2 SQLite `opencode.db` 请求级 tokens；兼容旧版 JSON / jsonl |
| 任意目录 | `--path <dir\|file>` | — | 通用字段探测 |

> 「未验证」＝本项目没用该平台真实日志跑通过，**不等于不支持**。别名：`claudecode` / `claude-code` → `claude_code`；
> `treacode` / `traecode` → `trae`。接入四步法见 [`docs/ADAPTERS.md`](docs/ADAPTERS.md)，欢迎带脱敏样例提 PR。

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 分层、数据流、技术选型、风险 |
| [`docs/ADAPTERS.md`](docs/ADAPTERS.md) | 平台接入四步法、字段探测优先级、常见坑 |
| [`docs/AGENT_INTEGRATION.md`](docs/AGENT_INTEGRATION.md) | 给其它 Agent 用的接口：CLI JSON / Python import / MCP / 一键脚本 |
| [`docs/CONTRACT.md`](docs/CONTRACT.md) | UsageRecord、计价口径、Summary JSON、MCP 协议 |
| [`docs/DESIGN_TOKENS.md`](docs/DESIGN_TOKENS.md) | 双主题令牌与厂商品牌色全表 |
| [`scripts/README-trae-capture.md`](scripts/README-trae-capture.md) | Trae 用量页抓取后导入 |

## 开发

```bash
python -m unittest discover -s tests -v        # 103 个用例
python scripts/smoke_mcp.py                    # MCP 握手端到端
python scripts/pack_skill.py                   # 打包 Skill 版 → dist/tokenboard-skill.tgz
```

CI 在 Ubuntu / macOS / Windows × Python 3.10–3.13 上跑同一套测试、CLI 冒烟、MCP 握手与 Skill 打包；
推 `v*` tag 会自动把 Skill 包挂到 GitHub Releases。贡献指南见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 隐私与免责

- 每次统计都是重新扫描现读日志源头，进程结束不落盘；没有本地累计数据库，也不需要清理缓存。
- **交互版把请求级明细（时间 / 模型 / 输入输出 / 缓存）嵌入 HTML** 以支持页内下钻，分享文件即等于分享这部分明细，对外分发前请确认，或改用 `--format json|table` 汇报。
- 服务版只监听 `127.0.0.1`，无鉴权，**不要直接用 `--host 0.0.0.0` 暴露到局域网或公网**。
- 金额是按内置牌价的粗略估算，不是账单；不同套餐请用 `--prices` 覆盖。
- 本项目与 DeepSeek / Anthropic / OpenAI / 腾讯 / WorkBuddy 等厂商无隶属关系，模型品牌色仅作数据区分用途。

## 致谢

交互设计受 [fuyi-git/token-dashboard](https://github.com/fuyi-git/token-dashboard) 启发，代码为本项目独立实现。

## License

[MIT](LICENSE)

# TokenBoard

> 多平台 LLM Token 消耗看板 · **本地服务版（可刷新）/ 静态 HTML 版（可分享）** · 可点击交互 · 零第三方依赖 · 数据不出本机

把 WorkBuddy、Claude Code、Codex、Trae、OpenCode 等平台的**请求级真实 usage**
统一成一张可交互看板：结论先行、可逐级下钻到每一次请求。
两种看法：起本地服务点「刷新」随时更新，或导出一个单文件离线 HTML 直接分发。
Python 3.10+ 标准库即可运行，不装包、不联网；静态快照不发任何网络请求，服务版只与本机回环地址通信。

![python](https://img.shields.io/badge/python-3.10%2B-blue)
![deps](https://img.shields.io/badge/dependencies-0-brightgreen)
![tests](https://img.shields.io/badge/tests-92%20passing-brightgreen)
![license](https://img.shields.io/badge/license-MIT-green)

## 特性

- **结论优先**：先回答「花了多少 / 命中多少 / 花在哪」，KPI 行一次给出合计 / 轮次 / 命中 / 金额与日均 / 会话 / 输入输出比，再给模型构成、数据源状态、时间分布三层下钻。
- **多平台统一**：一个 `UsageRecord` 契约吃下 6 类日志；新增平台只写一个 adapter（四步法见文档）。
- **页面可交互**：周期胶囊、日期范围与**指定日日历**都真切换（请求级明细嵌入页面，JS 按同一口径重算）、
  工作空间 → 会话 → 请求三级下钻、模型点选聚焦、跟随式悬浮明细、单文件离线全都有。
  **页面默认聚焦「1 天」**；扫描本身仍是全历史、明细全量嵌入，所以随时可切到近 30 天或「总量」，不会丢数据。
- **当日对齐**：所有「近 N 天」与日活日/周/月视图都以**生成当日**为锚点、按自然日计算，
  不是从最后一条日志往前推的滚动小时窗；空窗日留白，周期口径与页眉「数据截至」一致。
- **指定日查看**：除 1/3/7/30 天周期、自定义日期区间与「总量」外，**点击「指定日」整颗 pill 即弹出原生日历，
  选定后 pill 直接显示该日期并高亮**；所有卡片（含 0—24 时分布、日活热力锚点）只聚合这一天，
  可选范围自动限制在日志真实覆盖的日期内，无请求的日子给出明确空态。与周期胶囊、日期区间互斥，切换任一方即退出单日模式。
- **总量视图**：周期胶囊末位的「**总量**」按钮跨全部日期累计消耗，不受近 N 天窗口限制，
  一眼看穿整个历史区间的总 Token / 金额。
- **页面刷新（实时服务）**：`tokenboard serve` 启动本地服务，页面「**刷新**」按钮直接重新扫描本机日志拉取最新数据，
  无需退出重启；双击静态 `tokenboard.html` 时刷新仅重载当前快照。
- **单平台导入（只认本机真实数据）**：数据源表「**导入状态**」列按本机是否真有日志判定——
  **本机发现日志文件（文件列 > 0）→「✓ 已导入」+「已验证」+「重新导入」；
  本机未安装 / 0 文件 →「未导入」+「未验证」+「导入」按钮**。点击「导入」等于让服务端真扫一遍并
  检测本机安装状态：只有确实扫到记录才变「已导入 / 已验证 / 重新导入」并重载并入看板；
  0 条记录则明确提示「本机未安装或暂无日志，未导入数据」，状态列与导入按钮保持原样，绝不假装成功。
  对 `auto_discover=False` 的平台（Claude Code / Codex / Trae）尤其有用——它们默认不参与自动扫描。
  导入集合**只存本次 serve 进程内存**（不落盘），重启服务后需重新导入；
  双击静态文件打开时按钮会明确提示需用 `./serve.command` 实时模式。
- **诚实**：导入状态与「状态」列只认本机真实日志，不采用适配器开发期的 `verified` 静态标记
  （该标记仍保留给 CLI / MCP / JSON 出口）；本机未安装的平台明确标「未验证 / 未导入」；
  窗口内只有部分天数有数据时，结论条直接说明，空窗不摊薄日均。
- **零依赖**：运行期只用 Python 标准库；静态快照无 CDN、无外部字体、不发起任何网络请求；
  serve 模式下页面仅与本机 `127.0.0.1` 通信，日志数据不出本机。

## 看板里有什么

| 分区 | 内容 |
|---|---|
| 结论条 + KPI | 合计 Token · 请求次数 · 预估金额 · 折合单价；缓存命中率、请求轮次、日均（有数据天）、会话、输入输出比 |
| 01 模型与品牌色 | 按模型消耗（同厂商明度阶梯）、每日按模型堆叠柱 |
| 02 数据源状态 | 各平台日志目录、文件数、状态、**导入状态**（每行「导入」按钮；只认本机真实日志，点击后检测安装状态并单平台重扫接入） |
| 03 使用分布与时间节律 | 按模型消耗条 · 工作空间活跃分布（**TOP 5/10/全部 页内可切，默认 TOP 10**；可搜索/排序，长列表限高滚动、表头吸顶）· 会话消耗榜（**TOP 5/10/全部 页内可切，默认 TOP 10**；长列表限高滚动）· 单模型总量统计（按 Token/按金额切换）· 0—24 时分布·按模型（**窗口累计 / 仅当日 页内可切**；窗口累计为同一时段跨日累加、非当日实时，仅当日显示当天逐时消耗、未来时段为 0；悬浮竖线看该小时分模型消耗）· 单次请求大小分布（**TOP 2/3/5/8/全部 页内可切，默认 TOP 3**；p50/p90 + 全局 50% 基准，p90 圆点跟随模型色、悬浮看该模型「90% 请求 ≤ X token」）· 日活分布（时段占比 + 日/周/月视图；日/周为锚定生成当日的自然日序列，**月视图为当月 1 日至月末的完整自然月，未来日期留空不计入统计**） |

主题：浅色（白底荧光绿）默认，深色「暗夜玻璃」页面内一键切换并记忆。
配色规则：绿色系只用于 UI 框架，模型厂商品牌色只用于数据系列且永远附文字标签，
全表见 [`docs/DESIGN_TOKENS.md`](docs/DESIGN_TOKENS.md)。

## 快速开始 · 先选一个版本

三个版本**共用同一套扫描、归一化与计价代码**，数字口径完全一致，区别只在「怎么看」和「数据何时更新」：

| | **A · 本地服务版** | **B · 静态导出版** | **C · WorkBuddy Skill** |
|---|---|---|---|
| 一句话 | 常驻服务，点「刷新」就更新 | 双击导出一个 HTML 文件 | 在对话里说一句话生成看板 |
| 适合谁 | 每天看、边用边刷新 | 归档 / 发给别人 / 离线查看 | 不想开终端，让 Agent 帮你查 |
| 入口 | `./serve.command` | `./export.command` | 导入 `tokenboard-skill.tgz` |
| 产物 | 不产出文件，页面现场生成 | `tokenboard.html`（单文件离线） | Agent 生成的 HTML |
| 在哪看 | 浏览器 `http://127.0.0.1:8000/` | 双击该 HTML，任意浏览器 | WorkBuddy 内直接打开 |
| 数据怎么更新 | 页面「刷新」重新扫描本机日志 | 重新运行脚本、覆盖文件 | 重新发起一轮对话 |
| 「导入」按钮 | 真扫描、真并入 | 提示改用 A 版 | 提示改用 A 版 |
| 常驻进程 | 是（关窗口即停） | 否（跑完即结束） | 否 |
| 能分享吗 | 否（仅本机回环地址） | 可以（注意内含明细） | 生成的文件可分享 |

> 一句话挑：自己天天看 → **A**；要一个能发出去的文件 → **B**；想在对话里问 → **C**。
>
> 三个版本都**不需要 pip install**：Python 3.10+ 标准库即可，仓库内双击脚本会自动设置好路径。

---

### 版本 A · 本地服务版（可刷新更新数据）

**macOS 双击**：在 Finder 里双击 `serve.command`（首次被系统拦截就右键 → 打开）。
终端窗口常驻，浏览器自动打开看板。

**终端 / Windows / Linux**：

```bash
# 仓库内（macOS / Linux）
./serve.command                          # 默认 8000 端口，自动开浏览器
./serve.command --port 9000              # 换端口
./serve.command --since 7d --theme dark  # 每次刷新都按近 7 天口径重扫

# 已 pip 安装（任意系统）
tokenboard serve --open
tokenboard serve --port 9000 --open

# 克隆源码、不装包
PYTHONPATH=src python -m tokenboard serve --open                 # macOS / Linux
$env:PYTHONPATH="src"; python -m tokenboard serve --open         # Windows PowerShell
```

**怎么查看**：浏览器打开 `http://127.0.0.1:8000/`（改了 `--port` 就用新端口）。
服务只监听 `127.0.0.1`，不对外暴露，日志数据不出本机。

**怎么更新数据**：点页面右上角「**刷新**」——服务端重新扫描本机日志、重新渲染整页，
不用退出、不用重启。数据源表里的「导入」按钮也只有在这个版本能真正扫描并接入平台。

**怎么停**：关掉那个终端窗口，或在窗口内按 `Ctrl+C`。

**参数**：`--port` / `--host` / `--since` / `--until` / `--platform` / `--theme` / `--title` / `--prices`。
不带 `--since` 时扫描仍是全历史，页面默认聚焦「1 天」，可随时切近 30 天或「总量」。
每次请求都是**重新统计**：不落盘、没有本地累计库。导入集合只存本次服务进程内存，重启后需重新点导入。

#### 「导入」按钮到底在做什么（常见误解）

**不需要在对应平台里接入任何 skill 或插件。** TokenBoard 读的是各软件**自己写在本机磁盘上的会话日志**：

| 平台 | 默认读取位置 |
|---|---|
| WorkBuddy | `~/.workbuddy/projects` |
| Claude Code | `~/.claude/projects`、`~/.config/claude/projects` |
| OpenAI Codex CLI | `~/.codex/sessions`、`~/.codex/history` |
| Trae / TraeCode | `~/.trae-cn/hub_event_cache` |
| OpenCode | `~/.config/opencode`、`~/.local/share/opencode` |

这些日志是软件日常运行时自动落盘的，与 TokenBoard 装没装、装没装成 Skill 都无关。
点「导入」= 让服务端**直接读这个目录**，并把该平台纳入本次服务的统计范围；
不连平台账号、不需要平台侧配合，也不是在给平台装东西。

所以能不能拿到数据只取决于一件事：**本机装没装这个软件、它有没有产生可读日志**。
表里「文件 = 0」就是没扫到日志文件，点导入也拿不到数据，页面会明确提示「本机未安装或暂无日志，未导入数据」。
想让它有数据，只有三条路：

1. 安装并实际使用该平台、产生会话日志，再回来点「导入」；
2. 日志不在默认位置时，用版本 B 的 `tokenboard scan --path <真实目录>` 直接指定目录；
3. 像 Trae 那样主要历史落在加密 `database.db` 的，从客户端导出 CSV / JSON，再用 `tokenboard import` 导入（见下文）。

> 「WorkBuddy Skill」（版本 C）是 **TokenBoard 自己**被安装成技能的方式，决定的是「怎么发起查看」，
> 不是「数据从哪来」——它不会给 Claude Code / Codex 凭空变出日志。
>
> 另：`auto_discover=False` 的平台（Claude Code / Codex / Trae）默认不参与自动扫描，
> 「导入」按钮的真实作用正是**按需把它们接进统计**；本机真有日志时点一下就能并入看板。

---

### 版本 B · 静态导出版（直接运行就导出 HTML）

**macOS 双击**：双击 `export.command` → 扫描本机日志 → 生成 `tokenboard.html` → 自动用浏览器打开，
跑完进程即结束，不留下常驻服务。

**终端 / Windows / Linux**：

```bash
# 仓库内（macOS / Linux）
./export.command                                  # 产物：./tokenboard.html
./export.command --out ~/Desktop/看板-1108.html   # 自定义产物路径
./export.command --since 30d --theme dark         # 导出近 30 天 / 深色

# 已 pip 安装（任意系统）
tokenboard scan --open
tokenboard scan --since 7d --out week.html

# 克隆源码、不装包
PYTHONPATH=src python -m tokenboard scan --open                            # macOS / Linux
$env:PYTHONPATH="src"; python -m tokenboard scan --open --out 看板.html    # Windows PowerShell
```

**怎么查看**：直接双击生成的 HTML，任意浏览器都能打开。完全自包含——无 CDN、无外部字体、
不发任何网络请求，断网、拷到 U 盘、发给同事都能看；页内交互（周期切换、指定日、三级下钻、
模型聚焦、总量）全部保留。

**怎么更新数据**：重新运行一次 `./export.command` 覆盖同一份文件即可。
页面「刷新」按钮**只重载这份快照**，不会回读本机新日志（按钮会明确提示）；
数据源表的「导入」按钮同样提示改用 `./serve.command`。

**注意**：HTML 里嵌了请求级明细（时间 / 模型 / 输入输出 / 缓存），分享出去等于分享这部分数据，
对外分发前请确认（见「隐私与免责」）。仓库内 `tokenboard.html` 已被 `.gitignore` 排除，不会提交到 GitHub。

**参数**：`--out` / `--since` / `--until` / `--platform` / `--path` / `--theme` / `--prices` / `--title`；
`--format json` 或 `--format table` 可直接输出结构化数据给脚本 / Agent 用。

---

### 版本 C · WorkBuddy Skill（可直接导入）

装成 WorkBuddy 技能后，在对话里说「看看我的 token 用量」就能生成看板，不用记命令。

**方式 1 · 导入打包好的 Skill（推荐，免 clone）**

```bash
mkdir -p ~/.workbuddy/skills

# 方式 1a：从 GitHub Releases 下载 tokenboard-skill.tgz 到当前目录
tar -xzf tokenboard-skill.tgz -C ~/.workbuddy/skills

# 方式 1b：不想等 Release，就在仓库里自己打一个（产物在 dist/）
python scripts/pack_skill.py            # → dist/tokenboard-skill.tgz
tar -xzf dist/tokenboard-skill.tgz -C ~/.workbuddy/skills
```

包内条目自带 `tokenboard/` 前缀，**不要加 `--strip-components`**。解压后应为：

```
~/.workbuddy/skills/tokenboard/
  ├── SKILL.md
  ├── scripts/gen_dashboard.py
  └── src/tokenboard/
```

**方式 2 · 直接 clone 整个仓库**

```bash
git clone https://github.com/Rockspace007/TokenBoard.git ~/.workbuddy/skills/tokenboard
```

重启 WorkBuddy 会话，说「看看我的 token 用量」「生成本周消耗看板」「对比各平台用量」「token 审计」即可触发。

Skill 版走 `scripts/gen_dashboard.py` 薄壳，与 A / B 版共用 `src/tokenboard`，统计口径完全一致；
它产出的是**静态 HTML（同版本 B）**，不会启动服务，想点刷新更新仍请用版本 A。
安装不完整的典型症状是找不到 `src/tokenboard/__init__.py`——只复制 `SKILL.md` 会导致这个错误。

---

### 进阶 · pip 安装与 MCP Server

**pip 安装**（拿到全局 `tokenboard` 命令，A / B 两版都能用命令直接跑）：

```bash
pip install git+https://github.com/Rockspace007/TokenBoard.git

tokenboard platforms                    # 看本机有哪些平台日志
tokenboard scan                         # 版本 B：生成 ./tokenboard.html
tokenboard scan --since 7d --out week.html
tokenboard scan --format json           # 结构化输出，给脚本 / Agent 用
tokenboard serve --open                 # 版本 A：本地实时看板
tokenboard probe --path ~/some/logs     # 新平台接入前先看字段命中率
```

**MCP Server**（给其它 AI Agent 用）：

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

暴露 4 个工具：`tokenboard_scan` / `tokenboard_render` / `tokenboard_platforms` / `tokenboard_brands`。
传输为 stdio JSON-RPC，零依赖手写，不监听端口。协议见 [`docs/CONTRACT.md`](docs/CONTRACT.md)。

---

> **旧入口说明**：`./see.command` 仍然可用，等价于 `./serve.command`；
> `./see.command --static` 等价于 `./export.command`。仅为兼容已有双击习惯保留，新用法请直接用上面两个脚本。

## 常用参数

| 参数 | 说明 |
|---|---|
| `--platform` | 只扫指定平台，可重复 |
| `--path` | 自定义日志目录/文件；给定后忽略 `--platform` |
| `--since 7d` / `--until 2026-11-05` | 时间窗，支持 `YYYY-MM-DD` 与 `Nd`；页面内仍可切换周期 |
| `--out` | 输出路径，HTML 默认 `tokenboard.html` |
| `--open` | `scan` 写完 HTML / `serve` 起服务后自动打开浏览器 |
| `--format html\|json\|table` | 输出形态 |
| `--theme dark\|light` | light=白底荧光绿（默认）/ dark=暗夜玻璃，页面内可切换 |
| `--prices <json>` | 覆盖牌价：`{"glm":[2,8,0.4]}` |
| `--title` / `--window-note` | 自定义标题 / 结论条数据覆盖提示 |

子命令：`scan`（默认）、`serve`、`import`、`platforms`、`brands`、`probe`、`serve-mcp`。
上表参数是 `scan` / `import` 的；`serve` 额外用 `--host` / `--port`（默认 `127.0.0.1:8000`），
其余支持 `--since` / `--until` / `--platform` / `--theme` / `--title` / `--prices` / `--open`。

### 导入外部用量文件

平台只有加密数据库、没有明文日志时，可把客户端导出的 CSV / JSON 导入：

```bash
tokenboard import usage.csv --platform trae --format table
tokenboard import usage.json \
  --map ts=created_at --map input_tokens=prompt_tokens \
  --map output_tokens=completion_tokens --format html --out dist/tokenboard-import.html
```

`--map FIELD=SOURCE` 可重复，`FIELD` 取 `ts` / `platform` / `workspace` / `session_id` /
`model` / `title` / `input_tokens` / `output_tokens` / `cache_read_tokens` /
`cache_write_tokens` / `total_tokens` / `dedup_key`；未映射字段走通用别名探测。

JSON 响应默认自动寻找 `records` / `data` / `items` / `usages` 下的记录数组；结构更深时
用 `--records data.items` 指定点分路径。

Trae 用量页可以用真实浏览器会话抓取，再走上面的 `import`（不读取客户端 JWT）：
见 [`scripts/README-trae-capture.md`](scripts/README-trae-capture.md)。

## 平台支持矩阵

| 平台 | 参数 | 本机验证 | 说明 |
|---|---|---|---|
| WorkBuddy | `--platform workbuddy` | ✅ 已用真实日志验证 | `providerData.rawUsage`；子代理归属父会话 |
| Claude Code | `--platform claude_code` | ❌ 未验证 | `message.usage.*` |
| OpenAI Codex CLI | `--platform codex` | ❌ 未验证 | `token_count` 增量事件；已排除累计值 |
| Trae / TraeCode | `--platform trae` | ⚠️ 部分验证 | 仅 `~/.trae-cn/hub_event_cache` 的 `token_usage` 事件明文可读；按 `task_id`+请求 ID/`seq` 去重，缺失/null 的缓存字段记为未知而非 0；其余会话历史在加密 `database.db` |
| OpenCode | `--platform opencode` | ✅ 已用真实日志验证 | V2 SQLite 会话库 `opencode.db` 的请求级 tokens（缓存与 reasoning 已换算）；兼容旧版整文件 JSON 与 jsonl |
| 任意目录 | `--path <dir\|file>` | — | 通用字段探测 |

> 「未验证」= 本项目没用该平台真实日志跑通过，**不等于不支持**。
> 只有 `auto_discover=True` 的平台参与无参数自动扫描，避免把配置目录当日志扫；
> 其余平台可在服务版点「导入」按需接入，或用 `--platform` / `--path` 显式指定。
> 欢迎带脱敏样例提 PR，接入四步法见 [`docs/ADAPTERS.md`](docs/ADAPTERS.md)。
> 别名：`claudecode` / `claude-code` → `claude_code`；`treacode` / `traecode` → `trae`。

## 测试与验证

```bash
python -m unittest discover -s tests -v        # 92 个用例
python scripts/smoke_mcp.py                    # MCP 握手端到端
python -m tokenboard scan --path tests/fixtures/workbuddy.jsonl --format table
python -m tokenboard probe --path <日志目录>   # 字段命中率
```

CI 在 Ubuntu / macOS / Windows × Python 3.10–3.13 上跑同一套测试、CLI 冒烟、
MCP 握手与 Skill 打包；打 `v*` tag 会自动把 Skill 包挂到 GitHub Releases。

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 分层、数据流、技术选型对比、dev/prod 差异、风险 |
| [`docs/ADAPTERS.md`](docs/ADAPTERS.md) | 平台接入四步法、字段探测优先级、常见坑 |
| [`docs/AGENT_INTEGRATION.md`](docs/AGENT_INTEGRATION.md) | 给其它 agent 应用的导入接口：CLI JSON / Python import / MCP / 一键脚本 |
| [`docs/CONTRACT.md`](docs/CONTRACT.md) | UsageRecord、计价口径、Summary JSON、MCP 协议 |
| [`docs/DESIGN_TOKENS.md`](docs/DESIGN_TOKENS.md) | 双主题令牌与厂商品牌色全表 |

## 隐私与免责

- 只读取 usage、时间戳、模型名、会话 ID、工作空间目录名；**不读取也不输出消息正文**。
- **静态导出版**生成的 HTML 完全离线：无 CDN、不发起任何网络请求、无外部字体；主题偏好存 localStorage。
  **本地服务版**页面只与 `127.0.0.1` 通信（「刷新」重载页面、「导入」调 `/api/import`），同样不出本机。
- **每次统计都是重新统计**：扫描现读日志源头，进程结束不落盘；没有本地累计数据库，
  也不需要清理任何缓存。
- 本机数据不进 git：`tokenboard.html` / `dist/` / `data/` / `*.db` 均在 `.gitignore`
  排除清单里，正常提交不会把已统计的数据带上 GitHub。
- **注意**：交互版把请求级明细（时间/模型/输入输出/缓存）嵌入 HTML 以支持页内下钻，
  把文件分享出去即等于分享这部分明细；对外分发前请确认，或改用 `--format json|table` 汇报。
- 金额是按内置**牌价**的粗略估算，不是账单；不同套餐请用 `--prices` 覆盖。
- 本项目与 DeepSeek / Anthropic / OpenAI / 腾讯 / WorkBuddy 等厂商无隶属关系，
  模型品牌色仅作数据区分用途。

## 路线图

- [x] 多平台适配、双主题 + 品牌色、CLI + MCP + Skill、测试与文档
- [x] 页内交互引擎：周期/日期区间/指定日切换、三级下钻、模型聚焦、悬浮明细
- [x] 用真实日志验证 OpenCode（V2 SQLite `opencode.db`；Trae 已完成 `hub_event_cache` 部分验证）
- [ ] 用真实日志验证 Claude Code / Codex（欢迎补全样例）
- [ ] 流式聚合，支撑十万级以上请求
- [ ] 桌宠 P0（Web Widget）→ P1（Tauri 独立桌宠），见可行性报告

## 致谢

交互与功能设计部分受 [fuyi-git/token-dashboard](https://github.com/fuyi-git/token-dashboard) 启发
（周期切换、工作空间下钻、模型聚焦、日×时热力等交互思路）。

TokenBoard 在其思路之上**独立重写**为多平台、多入口、可测试的工程化实现：
代码架构、平台适配器、计价口径、测试与文档均为本项目原创，未复制其源代码。
参考项目目前未附带开源许可证（all rights reserved），本项目的 MIT 授权范围仅覆盖
TokenBoard 自有代码，不构成对参考项目的再分发许可。

## License

[MIT](LICENSE)

# TokenBoard

> 多平台 LLM Token 消耗看板 · 单文件离线 HTML · **可点击交互** · 零第三方依赖 · 数据不出本机

把 WorkBuddy、Claude Code、Codex、Trae、OpenCode 等平台的**请求级真实 usage**
统一成一张单文件 HTML 看板：结论先行、可逐级下钻到每一次请求。
Python 3.10+ 标准库即可运行，不装包、不联网、不发 fetch。

![python](https://img.shields.io/badge/python-3.10%2B-blue)
![deps](https://img.shields.io/badge/dependencies-0-brightgreen)
![tests](https://img.shields.io/badge/tests-81%20passing-brightgreen)
![license](https://img.shields.io/badge/license-MIT-green)

## 特性

- **结论优先**：先回答「花了多少 / 命中多少 / 花在哪」，KPI 行一次给出合计 / 轮次 / 命中 / 金额与日均 / 会话 / 输入输出比，再给模型构成、数据源状态、时间分布三层下钻。
- **多平台统一**：一个 `UsageRecord` 契约吃下 6 类日志；新增平台只写一个 adapter（四步法见文档）。
- **页面可交互**：周期胶囊与日期范围**真切换**（请求级明细嵌入页面，JS 按同一口径重算）、
  工作空间 → 会话 → 请求三级下钻、模型点选聚焦、跟随式悬浮明细、单文件离线全都有。
- **诚实**：未用真实日志验证的平台明确标「未验证」、不参与默认扫描；
  窗口内只有部分天数有数据时，结论条直接说明，空窗不摊薄日均。
- **零依赖**：运行期只用 Python 标准库；HTML 无 CDN、无 fetch、无外部字体。

## 看板里有什么

| 分区 | 内容 |
|---|---|
| 结论条 + KPI | 合计 Token · 请求次数 · 预估金额 · 折合单价；缓存命中率、请求轮次、日均（有数据天）、会话、输入输出比 |
| 01 模型与品牌色 | 按模型消耗（同厂商明度阶梯）、每日按模型堆叠柱 |
| 02 数据源状态 | 各平台日志目录、文件数、已验证/未验证 |
| 03 使用分布与时间节律 | 工作空间活跃分布（可搜索/排序）· 单模型总量统计（按 Token/按金额切换）· 0—24 时分布·按模型（平滑曲线，悬浮竖线看该小时分模型消耗）· 单次请求大小分布（p50/p90 + 全局 50% 基准）· 日活分布（时段占比 + 日×时热力图） |

主题：浅色（白底荧光绿）默认，深色「暗夜玻璃」页面内一键切换并记忆。
配色规则：绿色系只用于 UI 框架，模型厂商品牌色只用于数据系列且永远附文字标签，
全表见 [`docs/DESIGN_TOKENS.md`](docs/DESIGN_TOKENS.md)。

## 快速开始

### 最快路径 · 仓库内一键入口

```bash
./see.command                # 现扫现出：重新扫描全部已验证平台 → 生成 tokenboard.html → 浏览器打开
./see.command --since 7d     # 只看近 7 天
./see.command --theme dark   # 暗夜玻璃主题

macOS 还可以在 Finder 里**双击 `see.command`**（参数可直接透传；
首次运行如被拦截：右键 → 打开）。

每次运行都是**重新统计**：不落盘、没有本地累计库。唯一产物 `tokenboard.html`
已被 `.gitignore` 排除，不会带着本机数据提交到 GitHub。

### 方式一 · pip 安装（CLI / MCP）

```bash
pip install git+https://github.com/Rockspace007/TokenBoard.git

tokenboard platforms                   # 看本机有哪些平台日志
tokenboard scan                        # 生成 ./tokenboard.html（近 30 天）
tokenboard scan --since 7d --out week.html
tokenboard scan --format json          # 结构化输出，给脚本 / Agent 用
tokenboard probe --path ~/some/logs    # 新平台接入前先看字段命中率
```

或克隆源码运行（不装包）：

```bash
git clone https://github.com/Rockspace007/TokenBoard.git && cd TokenBoard
PYTHONPATH=src python -m tokenboard scan
```

### 方式二 · WorkBuddy Skill（对话内使用）

```bash
# 方式 A：Release 下载（免 clone）
#   从 GitHub Releases 下载 tokenboard-skill.tgz，然后：
mkdir -p ~/.workbuddy/skills
tar -xzf tokenboard-skill.tgz -C ~/.workbuddy/skills

# 方式 B：直接 clone（整个仓库即合法 Skill）
git clone https://github.com/Rockspace007/TokenBoard.git ~/.workbuddy/skills/tokenboard
```

重启 WorkBuddy 会话后，说「看看我的 token 用量」「生成本周消耗看板」即可触发。

### 方式三 · MCP Server（给 AI Agent 用）

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

## 常用参数

| 参数 | 说明 |
|---|---|
| `--platform` | 只扫指定平台，可重复 |
| `--path` | 自定义日志目录/文件；给定后忽略 `--platform` |
| `--since 7d` / `--until 2026-11-05` | 时间窗，支持 `YYYY-MM-DD` 与 `Nd`；页面内仍可切换周期 |
| `--out` | 输出路径，HTML 默认 `tokenboard.html` |
| `--open` | 写完 HTML 后直接用浏览器打开看板 |
| `--format html\|json\|table` | 输出形态 |
| `--theme dark\|light` | light=白底荧光绿（默认）/ dark=暗夜玻璃，页面内可切换 |
| `--prices <json>` | 覆盖牌价：`{"glm":[2,8,0.4]}` |
| `--title` / `--window-note` | 自定义标题 / 结论条数据覆盖提示 |

子命令：`scan`（默认）、`import`、`platforms`、`brands`、`probe`、`serve-mcp`。

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
> 只有已验证平台参与无参数自动扫描，避免把配置目录当日志扫。
> 欢迎带脱敏样例提 PR，接入四步法见 [`docs/ADAPTERS.md`](docs/ADAPTERS.md)。
> 别名：`claudecode` / `claude-code` → `claude_code`；`treacode` / `traecode` → `trae`。

## 测试与验证

```bash
python -m unittest discover -s tests -v        # 81 个用例
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
| [`docs/DESKTOP_PET_FEASIBILITY.md`](docs/DESKTOP_PET_FEASIBILITY.md) | 桌宠可行性调研与路线对比 |

## 隐私与免责

- 只读取 usage、时间戳、模型名、会话 ID、工作空间目录名；**不读取也不输出消息正文**。
- 生成的 HTML 完全离线：无 CDN、无 fetch、无外部字体；主题偏好存 localStorage。
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
- [x] 页内交互引擎：周期/日期切换、三级下钻、模型聚焦、悬浮明细
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

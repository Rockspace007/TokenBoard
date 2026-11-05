# TokenBoard

> 多平台 LLM Token 消耗看板 · 绿色系 UI + 模型厂商品牌色 · 零第三方依赖 · 数据不出本机

把 WorkBuddy、Claude Code、Codex、Trae、OpenCode 等平台的**请求级真实 usage**
统一成一张单文件离线 HTML 看板。Python 3.10+ 标准库即可运行，不装包、不联网、不发 fetch。

![theme](https://img.shields.io/badge/theme-green%20%2B%20brand--colors-1F6F63)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![deps](https://img.shields.io/badge/dependencies-0-brightgreen)

## 为什么又做一个

现有看板通常只认一个平台的日志、把所有图表等权平铺。TokenBoard 解决三件事：

1. **多平台统一**：一个 `UsageRecord` 契约吃下 6 类日志，新增平台只写一个 adapter。
2. **结论优先**：先给「花了多少 / 命中多少 / 花在哪」，再给构成、时间、模型三层下钻。
3. **诚实**：未用真实数据验证的平台明确标「未验证」、不参与默认扫描；
   「近 30 天」窗口只有 3 天数据时会在结论条上直说，空窗不摊薄日均。

**配色规则**：绿色系只用于 UI 框架（`bg #0E1A16` / `brand #1F6F63`），
模型厂商品牌色只用于数据系列，且永远附文字标签。详见 [`docs/DESIGN_TOKENS.md`](docs/DESIGN_TOKENS.md)。

## 两个版本

用户要的「agent tool 版」和「skill 版」**是同一仓库的两个入口，不是两份代码**，
因此统计口径、价格表、品牌色只维护一份。

| 版本 | 安装 | 给谁用 | 入口 |
|---|---|---|---|
| **agent tool** | `pip install -e .` | 人 / AI Agent | `tokenboard ...`（CLI）、`tokenboard serve-mcp`（MCP Server） |
| **Skill** | `git clone <repo> ~/.workbuddy/skills/tokenboard` | WorkBuddy 对话 | `SKILL.md` → `scripts/gen_dashboard.py` |

### 快速开始 · agent tool

```bash
git clone <your-repo-url> tokenboard && cd tokenboard
pip install -e .                       # 或：export PYTHONPATH="$PWD/src"

tokenboard platforms                   # 看本机有哪些平台日志
tokenboard scan                        # 生成 ./tokenboard.html
tokenboard scan --since 7d --theme light --out week.html
tokenboard scan --format json           # 结构化输出，给脚本/Agent 用
tokenboard probe --path ~/some/logs     # 新平台接入前先看字段命中率
```

### 快速开始 · MCP Server

在 MCP client 配置里加（路径换成你的绝对路径）：

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
传输是 stdio、每行一个 JSON-RPC 消息，零依赖手写，不监听端口。协议见 [`docs/CONTRACT.md`](docs/CONTRACT.md)。

### 快速开始 · Skill

```bash
# 方式一：整个仓库即合法 Skill
git clone <your-repo-url> ~/.workbuddy/skills/tokenboard

# 方式二：只装最小包
python scripts/pack_skill.py            # 产出 dist/tokenboard-skill.tgz
```

重启 WorkBuddy 会话后，说「看看我的 token 用量」即可触发。
注意 Skill 目录必须包含 `src/`，只复制 `SKILL.md` 会半安装并给出明确报错。

## 平台支持矩阵

| 平台 | 参数 | 本机验证 | 说明 |
|---|---|---|---|
| WorkBuddy | `--platform workbuddy` | ✅ 已用真实日志验证 | `providerData.rawUsage`；子代理归属父会话 |
| Claude Code | `--platform claude_code` | ❌ 未验证 | `message.usage.*`；本机未安装 |
| OpenAI Codex CLI | `--platform codex` | ❌ 未验证 | `token_count` 增量事件；已排除累计值 |
| Trae / TraeCode | `--platform trae` | ❌ 未验证 | 本机 `~/.trae-cn` 下只有会话记忆，无 usage 字段 |
| OpenCode | `--platform opencode` | ❌ 未验证 | 支持整文件 JSON 与 jsonl |
| 任意目录 | `--path <dir\|file>` | — | 通用字段探测 |

> 「未验证」= 本项目没用该平台真实日志跑通过，**不等于不支持**。
> 只有已验证平台参与无参数自动扫描，避免把配置目录当日志扫。
> 接入新平台的四步法见 [`docs/ADAPTERS.md`](docs/ADAPTERS.md)。

别名：`claudecode`、`claude-code` → `claude_code`；`treacode`、`traecode` → `trae`。

## 常用参数

| 参数 | 说明 |
|---|---|
| `--platform` | 只扫指定平台，可重复 |
| `--path` | 自定义日志目录/文件；给定后忽略 `--platform` |
| `--since 7d` / `--until 2026-11-05` | 时间窗，支持 `YYYY-MM-DD` 与 `Nd` |
| `--out` | 输出路径，HTML 默认 `tokenboard.html` |
| `--format html\|json\|table` | 输出形态 |
| `--theme dark\|light` | 深绿 / 浅绿 |
| `--prices <json>` | 覆盖牌价：`{"glm":[2,8,0.4]}` |
| `--window-note` | 写在结论条上的数据覆盖提示 |

子命令：`scan`（默认）、`platforms`、`brands`、`probe`、`serve-mcp`。

## 测试与验证

```bash
python -m unittest discover -s tests -v        # 43 个用例
python scripts/smoke_mcp.py                    # MCP 握手端到端
python -m tokenboard scan --format table       # 真实数据冒烟
python -m tokenboard probe --path <日志目录>   # 字段命中率
```

CI 在 Ubuntu / macOS / Windows × Python 3.10–3.13 上跑同一套测试与 MCP 自检。

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 分层、数据流、技术选型对比、dev/prod 差异、风险 |
| [`docs/ADAPTERS.md`](docs/ADAPTERS.md) | 平台接入四步法、字段探测优先级、常见坑 |
| [`docs/CONTRACT.md`](docs/CONTRACT.md) | UsageRecord、计价口径、Summary JSON、MCP 协议 |
| [`docs/DESIGN_TOKENS.md`](docs/DESIGN_TOKENS.md) | 绿色主题令牌与厂商品牌色全表 |
| [`docs/DESKTOP_PET_FEASIBILITY.md`](docs/DESKTOP_PET_FEASIBILITY.md) | 桌宠可行性：三个上游仓库调研、三条路线对比、架构与风险 |

## 路线图

- [x] 多平台适配、绿色色调 + 品牌色、CLI + MCP、Skill、测试与文档
- [ ] 用真实日志验证 Claude Code / Codex / Trae / OpenCode（欢迎带脱敏样例提 PR）
- [ ] 流式聚合，支撑十万级以上请求
- [ ] 桌宠 P0（Web Widget）→ P1（Tauri 独立桌宠），见可行性报告

## 隐私与免责

- 只读取 usage、时间戳、模型名、会话 ID、工作空间目录名；**不读取也不输出消息正文**。
- 生成的 HTML 完全离线：无 CDN、无 fetch、无外部字体；主题偏好存 localStorage。
- 金额是按内置**牌价**的粗略估算，不是账单；不同套餐请用 `--prices` 覆盖。
- 本项目与 DeepSeek / Anthropic / OpenAI / 字节 / WorkBuddy 等厂商无隶属关系，
  模型品牌色仅作数据区分用途。

## License

[MIT](LICENSE)

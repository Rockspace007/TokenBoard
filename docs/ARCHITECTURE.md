# TokenBoard 架构设计

## 1. 目标与约束

| 项 | 结论 |
|---|---|
| 目标 | 把多个 AI 编程平台的**请求级** Token 消耗统一成一张可离线查看的看板 |
| 使用人群 | 个人开发者 / 小团队，本机电量级数据（当前实测 906 条请求、27 个日志文件） |
| 访问规模 | 单机、单用户、无并发；不需要服务端、不需要数据库 |
| 部署环境 | macOS / Linux / Windows，Python 3.10+，无网络 |
| 硬约束 | 零第三方依赖；数据不出本机；CLI 与 Agent 调用口径一致 |

访问规模和"无服务端"这两条决定了架构：**不做 Web 服务、不做数据库、不做定时任务**，
生成一个自包含 HTML 就是最合适的交付物。

## 2. 分层与数据流

```
平台日志 (jsonl / json)
   └─ adapters/*  → 字段探测 + 路径发现 + 会话归属
        └─ UsageRecord（唯一内部数据契约）
             ├─ aggregate.summarize()  →  Summary（KPI / 分组 / 时间维度）
             │    └─ pricing.cost_cny()  →  按实际缓存命中计价
             └─ render.render_html()   →  单文件离线 HTML（绿色系 + 品牌色）
                    ↑ brands.theme() / brands.color_of() 提供唯一色源

入口层（三者共用上面同一条链路，不重复实现统计逻辑）
   ├─ CLI        tokenboard.cli        → 人用
   ├─ MCP Server tokenboard.mcp_server → Agent 用（stdio JSON-RPC）
   └─ Skill      scripts/gen_dashboard.py（薄壳，直接 import CLI）
```

**为什么把归一化放在最前面**：新增平台时只写一个 adapter，聚合/计价/渲染/两个入口
全都不用改；反过来如果每个入口各写一套解析，口径漂移是迟早的事。

## 3. 目录结构

```
TokenBoard/
├── SKILL.md                  # Skill 版入口（根目录即合法 Skill）
├── scripts/
│   ├── gen_dashboard.py      # Skill 薄壳
│   └── pack_skill.py         # 打包最小 Skill tgz
├── src/tokenboard/
│   ├── models.py             # UsageRecord / SourceStatus
│   ├── brands.py             # 绿色主题令牌 + 厂商品牌色（唯一色源）
│   ├── pricing.py            # 牌价表 + 缓存计价
│   ├── adapters/             # 6 个平台适配器 + 通用字段探测
│   ├── registry.py           # 注册表与统一 scan()
│   ├── aggregate.py          # 聚合
│   ├── render.py             # 单文件 HTML 渲染
│   ├── cli.py / __main__.py  # CLI
│   └── mcp_server.py         # 零依赖 MCP stdio server
├── tests/ + fixtures/        # unittest，零测试框架依赖
├── docs/                     # 本文、适配器指南、契约、令牌、桌宠可行性
└── .github/workflows/ci.yml  # 3.10/3.11/3.12/3.13 矩阵
```

## 4. 技术选型对比

| 方案 | 优点 | 缺点 | 适用 |
|---|---|---|---|
| **Python 3 标准库（选用）** | 零依赖、与现有 token-dashboard skill 同栈、单文件分发、CSV/JSON/SVG 都好写、MCP stdio 只需 `json`+`sys` | 做原生桌宠窗口要另起技术栈 | 本机数据工具、Skill、CLI |
| Node 22 + TypeScript | 与 DeepSeek Harness / dsh 插件生态同栈，未来做桌宠顺 | 需要 pnpm 依赖与构建链，安装门槛高 | 要做 DSH 插件时 |
| Python 内核 + Node MCP 壳 | 两头讨好 | 两套代码、两套发布、口径仍可能漂移 | 不推荐 |

**结论**：当前需求（看板 + Skill + Agent tool）用 Python 标准库成本最低；
只有当桌宠确定要绑定 DSH 生态时，才值得引入 Node。见 `DESKTOP_PET_FEASIBILITY.md`。

## 5. 两个版本的关系

用户要的「agent tool 版」与「skill 版」**不是两份代码**，而是同一仓库的两个入口：

| 版本 | 安装 | 调用方 | 入口 |
|---|---|---|---|
| agent tool | `pip install -e .` 或 `PYTHONPATH=src` | 人 / Agent | `python -m tokenboard ...`、`serve-mcp` |
| Skill | `git clone <repo> ~/.workbuddy/skills/tokenboard` | WorkBuddy 对话 | `SKILL.md` → `scripts/gen_dashboard.py` |

这样品牌色、计价、字段探测只维护一份。代价是 Skill 目录里必须包含 `src/`，
因此提供 `scripts/pack_skill.py` 生成自包含 tgz，避免只拷 `SKILL.md` 造成半安装。

## 6. dev / prod 差异

| 维度 | dev（本机原型） | prod（团队/长期用） |
|---|---|---|
| 价格表 | 内置 `DEFAULT_PRICES` 牌价 | 用 `--prices` 指向团队真实合同价，纳入版本管理 |
| 日志路径 | 默认探测各平台 home 目录 | 显式 `--path` 指向集中目录，避免权限问题 |
| 输出 | 当前目录 `tokenboard.html` | 指定 `--out` + 归档策略，定期清理 |
| 安全 | 单机可信 | MCP 的 `tokenboard_render` 限制只写 `.html`；`serve-mcp` 不监听端口、只走 stdio；不读取消息正文 |
| 校验 | `python -m unittest discover -s tests` | CI 4 个 Python 版本矩阵 + `probe` 命中率门槛 |

## 7. 风险与兜底

| 风险 | 表现 | 兜底 |
|---|---|---|
| 平台字段变更 | 解析命中率骤降、统计偏低 | `probe` 命令量化命中率；适配器字段表集中可改 |
| 未验证平台误扫 | 把配置/记忆目录当日志 | `auto_discover=False`，只有已验证平台参与默认扫描 |
| 累计值重复计数 | Codex `total_token_usage` 被逐行相加 | 只取 `last_token_usage`，测试锁死 |
| 缓存字段脏数据 | 命中数 > 输入数 → 负成本 | `extract_usage` 与 `cost_cny` 双重 clamp |
| 价格表不准 | 金额与实际账单对不上 | 页面明确写"按牌价粗略估算"，`--prices` 覆盖 |
| 大日志内存 | 一次性载入全部记录 | 当前万级无压力；十万级需改成流式聚合（见下） |

## 8. 性能与扩展点

- 当前 `scan()` 把所有记录放进内存，实测本机 906 条 / 27 文件耗时 < 1s。
- 十万条以上时，把 `summarize` 改成接收 iterator 并即时累加即可，
  `render` 只需 Summary（但每日堆叠图需要明细，可改成预聚合的 day×model 矩阵）。
- MCP 的 `tokenboard_scan` 只返回 KPI 与分组结果，不返回原始记录，避免撑爆 Agent 上下文。

## 9. 如何验证

```bash
python -m unittest discover -s tests -v      # 43 个用例
python -m tokenboard platforms                # 数据源状态
python -m tokenboard probe --path <日志目录>  # 新平台命中率
python -m tokenboard scan --format table      # 端到端冒烟
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python -m tokenboard serve-mcp
```

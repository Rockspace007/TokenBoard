# 平台适配器接入指南

## 1. 当前支持矩阵（2026-11-05 本机实测）

| 平台 key | 别名 | 默认日志路径 | 本机状态 | 自动扫描 | 验证 |
|---|---|---|---|---|---|
| `workbuddy` | `wb` | `~/.workbuddy/projects` | 27 个 jsonl | ✅ | **已用真实日志验证** |
| `claude_code` | `claudecode` / `claude-code` | `~/.claude/projects` | 未安装 | ❌ | 仅公开字段 |
| `codex` | — | `~/.codex/sessions`, `~/.codex/history` | 未安装 | ❌ | 仅公开字段 |
| `trae` | `treacode` / `traecode` | `~/.trae-cn` 等候选 | 41 个 jsonl，但**是会话记忆** | ❌ | 无 usage 字段 |
| `opencode` | `open-code` | `~/.local/share/opencode/opencode.db`（V2 SQLite）＋ 旧版 json/jsonl | 已有会话库 | ✅ | **已用真实日志验证** |
| `generic` | — | 无（需 `--path`） | 按需 | ❌ | 通用探测 |

> **关于 Trae**：本机 `~/.trae-cn/memory/projects/**/session_memory_*.jsonl` 的内容是
> `intent / actions / outcome / learned / message_summary_time`，属于会话摘要，
> **没有任何 usage 字段**。把它算进「平台文件数」但不参与扫描，是为了不虚报支持度。
> 真实用量日志路径待确认，欢迎带样例提 PR。

## 2. 「未验证」不是「不支持」

`platforms` 里的 `verified` 只表示**本项目有没有用该平台的真实日志跑通过**，
不代表代码不能读。判断依据是：

1. 有真实日志目录 → `probe` 命令给出「可完整归一化」百分比；
2. 有 fixture 覆盖主要字段变体 → 单元测试通过；
3. 三条全绿才把 `verified = True` 且 `auto_discover = True`。

在此之前该平台只能通过 `--platform <name>` 或 `--path <目录>` 显式指定。

## 3. 四步接入新平台

**Step 1 · 探路**（不要先写代码）

```bash
python -m tokenboard probe --path /真实/日志/目录
```

看三个数字：`usage 字段命中` / `时间戳字段命中` / `可完整归一化`。
最后一项低于 30% 说明该平台用了私有字段，需要写适配器。

**Step 2 · 留 fixture**

在 `tests/fixtures/<platform>.jsonl` 放 2–4 行真实脱敏日志（含一行无效行），
在 `tests/test_adapters.py` 加一条断言。

**Step 3 · 写适配器**

新建 `src/tokenboard/adapters/<platform>.py`，继承 `BaseAdapter`：

```python
from .base import BaseAdapter

class MyPlatformAdapter(BaseAdapter):
    name = "my_platform"
    display_name = "My Platform"
    root_globs = ("~/.my-platform/logs",)
    verified = False          # 跑通前不要改
    auto_discover = False     # 同上
    note = "待用真实日志验证"
```

只有平台特有结构才需要覆盖 `parse_line` / `make_context` / `iter_records`。
参考 `codex.py`（token_count 增量事件）与 `opencode.py`（SQLite 会话库，见下）。

**Step 4 · 注册并验证**

在 `registry.py` 的 `ADAPTER_CLASSES` / `ALIASES` 登记，然后：

```bash
python -m unittest discover -s tests -v
python -m tokenboard scan --platform my_platform --format table
```

全绿后再把 `verified` / `auto_discover` 改为 `True`，并更新本文的矩阵。

## 4. 通用字段探测优先级

`adapters/base.py` 按顺序尝试以下 usage 容器，命中第一个就停：

```
providerData.rawUsage → providerData.usage → message.usage → response.usage
→ body.usage → usage → tokens → （顶层扁平）
```

字段别名：

| 语义 | 别名 |
|---|---|
| 输入 | `prompt_tokens`, `input_tokens`, `inputTokens`, `input`, `promptTokens` |
| 输出 | `completion_tokens`, `output_tokens`, `outputTokens`, `output`, `completionTokens` |
| 总量 | `total_tokens`, `totalTokens`, `total`（缺失时由输入+输出推导） |
| 缓存读 | `prompt_cache_hit_tokens`, `cache_read_input_tokens`, `cached_tokens`（含 `prompt_tokens_details.*`） |
| 缓存写 | `cache_creation_input_tokens`, `cached_creation_tokens`, `cache_write_tokens` |
| 时间戳 | `timestamp`, `ts`, `time`, `created_at`, `datetime`, `date`, `@timestamp` |
| 模型 | `providerData.model`, `message.model`, `model`, `modelId` … |
| 会话 | `sessionId`, `conversationId`, `threadId` … |

**丢弃而不是猜测**：拿不到 usage 或时间戳的行直接跳过。因此统计值可能偏低，
但绝不会凭空造数——这是成本类工具最重要的诚实性。

## 5. OpenCode（SQLite 会话库）特例

OpenCode V2 不再写 jsonl，而是把会话落进单个 SQLite 库
`~/.local/share/opencode/opencode.db`（WAL 模式）。该适配器（`adapters/opencode.py`）
的开发要点：

| 要点 | 说明 |
|---|---|
| 请求级来源 | `session_message` 表 `type='assistant'` 行的 `data.tokens`，一行 = 一次模型请求 |
| 字段形态 | `{"input":..,"output":..,"reasoning":..,"cache":{"read":..,"write":..}}`；时间在 `data.time.created`（毫秒） |
| 口径换算 | `input` **不含**缓存（实测 cache.read > input）→ `UsageRecord.input_tokens = input + read + write`；`reasoning` 与 `output` **不相交** → `output_tokens = output + reasoning` |
| 会话归属 | `session_v2.parent_id` 非空是 task 子代理会话，归属父会话；workspace 取 `session_v2.directory` 的目录名 |
| 只读安全 | `mode=ro` 直连；失败时把 db + `-wal` + `-shm` 拷到临时目录重开副本，**不写原库** |
| 去重 | `dedup_key = "opencode:<message_id>"`，天然防重复计数 |
| 不信会话汇总 | `session_v2.tokens_*` 是只增不减的累计快照（重试不回减），会略大于消息明细之和 |

仅 `opencode.db` 这个文件名参与发现；其余 json/jsonl 按旧版解析逻辑保留。

## 6. 常见坑

| 坑 | 说明 |
|---|---|
| 累计值当增量 | Codex 的 `total_token_usage` 是累计，逐行相加会成倍虚高；只取 `last_token_usage` |
| 子代理算成独立会话 | WorkBuddy 的 `subagents/agent-*.jsonl` 必须归属父会话，否则会话数虚高 |
| 缓存命中 > 输入 | 不同平台字段口径不同，必须 clamp 到 input 内，否则算出负成本 |
| reasoning 当输出子集 | OpenCode 的 `reasoning` 与 `output` 不相交，`output_tokens = output + reasoning`，否则漏计思考 token |
| 整文件 JSON 用逐行解析 | OpenCode 之类会落单文件 JSON 数组，需走 `iter_json_document` |
| 毫秒时间戳 | `> 1e12` 要除以 1000；`< 1e9` 视为非时间戳直接丢弃 |
| 路径 slug 当工作空间名 | WorkBuddy 目录名是转义路径，需截 `-WorkBuddy-` 之后的部分 |
| 配置目录混入 | 目录里带 `*.jsonl` 不等于有用量日志，先 `probe` 再决定要不要加进 `root_globs` |

## 7. 隐私边界

适配器只读取 usage、时间戳、模型名、会话 ID 与工作空间目录名，
**不读取、不输出消息正文**。生成的 HTML 不含会话标题与提示词内容。

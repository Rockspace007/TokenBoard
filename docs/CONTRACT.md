# 数据契约

所有入口（CLI / MCP / Skill）与所有平台适配器共用本文件定义的结构。
改动契约必须同步更新 `src/tokenboard/models.py`、fixture 与测试。

## 1. UsageRecord（请求级，不是会话汇总）

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts` | int | Unix **秒**；毫秒入参自动换算 |
| `platform` | str | `workbuddy` / `claude_code` / `codex` / `trae` / `opencode` / `generic` |
| `workspace` | str | 工作空间短名 |
| `session_id` | str | 会话 ID；子代理归属父会话 |
| `model` | str | 归一化后的模型名 |
| `input_tokens` | int | 输入（含缓存读与缓存写） |
| `output_tokens` | int | 输出 |
| `cache_read_tokens` | int | 缓存读命中，已 clamp 到 ≤ input |
| `cache_write_tokens` | int | 缓存写入，已 clamp 到 ≤ input − cache_read |
| `total_tokens` | int | 缺失时由 input + output 推导 |

约束：所有数值字段非负；脏数据在 `UsageRecord.__post_init__` 里归零。
`non_cached_input = input − cache_read − cache_write`（下限 0）。

## 2. 时间语义

- 日志里的时间戳统一按**本机时区**解释，与用户在客户端看到的时间一致。
- CLI `--since` / `--until` 为 Unix 秒，区间 **`[since, until)`**。
- `active_days` 是「有数据的自然日」数量，不是窗口长度；日均按它算，
  空窗不摊薄。页面会明确写出这一点，避免"近 30 天"看起来像有 30 天数据。

## 3. 计价口径

单位 **元 / 百万 token**，价格表项 `[输入, 输出, 缓存读取]`：

```
成本 = (cache_read × 缓存价
      + cache_write × 输入价 × 1.25        # Claude 系缓存写入
      + (input − cache_read − cache_write) × 输入价
      + output × 输出价) / 1_000_000
```

- 按**每条请求**的实际缓存命中计价，不是拿总 token 乘单价。
- 价格表是牌价，不是账单；不同套餐/网关请用 `--prices` 覆盖：

```json
{ "glm": [2, 8, 0.4], "my-gateway": [1.5, 6, 0.3] }
```

- 默认表见 `src/tokenboard/pricing.py`。未知模型回退 `(2, 8, 0.4)`。

## 4. 主题与品牌色契约

见 `DESIGN_TOKENS.md`。代码里的**唯一色源**是 `src/tokenboard/brands.py`，
渲染层与 Ardot 设计稿都与它对齐。规则摘要：

- 绿色系 → 仅 UI 框架（背景/卡片/边框/文字/主按钮/热力阶）。
- 厂商品牌色 → 仅数据系列（柱/线/图例点/模型徽标）。
- 品牌色必须同时带文字标签，不依赖颜色单独传达信息（WCAG 1.4.1）。

## 5. Summary JSON（`--format json` / `tokenboard_scan`）

```jsonc
{
  "kpi": {
    "total_tokens": 0, "daily_average": 0, "requests": 0,
    "sessions": 0, "workspaces": 0, "input_output_ratio": 0,
    "cache_hit_rate": 0, "estimated_cost_cny": 0,
    "price_per_million_cny": 0, "active_days": 0
  },
  "models":    [{ "name": "", "tokens": 0, "requests": 0, "cost": 0,
                  "color": "#000000", "vendor": "" }],
  "platforms": [{ "name": "", "tokens": 0, "requests": 0 }],
  "workspaces":[{ "name": "", "tokens": 0, "requests": 0 }],
  "daily":     [{ "date": "YYYY-MM-DD", "tokens": 0 }],
  "hourly":    [ /* 24 个 int */ ],
  "bands":     [ /* 4 个 int：0-6 / 6-12 / 12-18 / 18-24 */ ],
  "coverage":  { "first_ts": 0, "last_ts": 0, "active_days": 0 },
  "sources":   [{ "name": "", "display_name": "", "verified": false,
                  "roots": [], "file_count": 0, "note": "" }],
  "errors":    []
}
```

`errors` 非空表示**部分平台扫描失败**，数据仍可用但不完整，调用方不得静默忽略。

## 6. MCP 协议

- 传输：**stdio，每行一个 JSON 消息**（JSON-RPC 2.0），不是 LSP 的 Content-Length。
- `protocolVersion`: `2024-11-05`；日志只写 stderr，stdout 多一行都会破坏协议流。
- notification（如 `notifications/initialized`）没有 `id`，**不回复**。

| 工具 | 作用 |
|---|---|
| `tokenboard_scan` | 返回上面的 Summary JSON（不含原始记录） |
| `tokenboard_render` | 生成 HTML，返回绝对路径 + 摘要；输出路径必须是 `.html` / `.htm` |
| `tokenboard_platforms` | 返回各平台 `SourceStatus` |
| `tokenboard_brands` | 返回主题令牌与品牌色表 |

`tools/call` 参数中 `platforms` 与 `paths` 互斥，`paths` 优先；
`since` / `until` 为 Unix 秒整数。工具异常以 `isError: true` 的 text content 返回，
不会让 server 崩溃。

配置示例（MCP client）：

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

# Trae 加密数据库调查结论 + 外部用量导入入口

## Context

用户要求查清 Trae `database.db` 能否用本机现有合法凭据读出用量表。若不可读，则落地「导入外部用量文件（CSV/JSON、字段映射可配）」入口，并有测试。

本轮已完成只读调查（未改 Trae 文件、未请求需登录态的远端接口），结论如下。

### 1. database.db 格式判定：SQLCipher 加密的 SQLite

证据链：

| 检测项 | 结果 |
| --- | --- |
| 主库大小 | 190,701,568 bytes（活动写入中） |
| 前 16 字节 | `89 6f 04 34 db 2e 71 8b f9 93 f3 dc 18 dc f9 8e`，不是 `SQLite format 3\0` |
| `file` 命令 | `data` |
| `sqlite3` 只读打开 | `Error: file is not a database (26)` |
| WAL 头 | `377f0682 002de218 00001000 ...`：标准 SQLite WAL magic，页大小 4096 |
| WAL 帧 0 | pageno 1，页前 16 字节与主库头完全一致（即 SQLCipher 的 salt） |
| 抽样熵 | 主库 16KB 块 7.987~7.991 bit/byte；WAL 页 7.951~7.962 bit/byte |
| 明文 SQL 扫描 | `CREATE TABLE` / `sqlite_master` / `SQLite` / `PRAGMA` / `SELECT` / `token` / `usage` 计数均为 0 |

应用侧证据（`/Applications/Trae CN.app/Contents/Resources/app/modules/ai-agent/libharness.dylib`）：

- 静态链接 SQLCipher（`otool -L` 无外部 sqlite 库）；
- 字符串含 `PRAGMA key = `、`sqlite3_key_v2`、`sqlite3_rekey_v2`、`sqlcipher_cipher_ctx_key_derive`、`PRAGMA cipher_page_size`、`PRAGMA cipher_compatibility`、`PRAGMA cipher_default_kdf_iter`、`cipher_default_hmac_algorithm`；
- 含 `harness/storage-db/src/store/sqlite_*_store` 模块路径。

判断：**SQLCipher 4.x 默认参数（4096 页、HMAC 开启）加密的 SQLite**，不是压缩容器，也不是自有格式。WAL 头保持明文是 SQLite/SQLCipher 的正常行为，可据此排除「纯压缩包」和「纯私有容器」。

### 2. 表结构：本机不可读，但可从二进制符号还原线索

`database.db` 无密钥无法 dump schema。`libharness.dylib` 中的 SQL 片段显示存在：

- `chat_message`、`chat_message_general`、`chat_session`、`im_session_*`、`project`
- 列/字段：`token_usage`、`item_token_usage`、`summary`、`created_at`、`agent_type`、`context_usage`、`accumulated_summary`、`compress_token_usage`
- turn store：`TurnRecord`、`context_usage`、`last_batch_seq`

即 Trae 的数据库里确实是**消息/请求级** token 记录，但加密不可读，无法确认具体行数、覆盖区间和字段口径。

### 3. 密钥材料：本机没有可直接使用的官方密钥

- `out/main.js` 无 `sqlcipher` 引用；传给 ai-agent 的环境变量只有 `DB_PATH`、`FILE_BASE_DIR`、`ICUBE_*` 池参数等，**无 DB key**。
- `~/.trae-cn` 配置（`installed-plugins.json`、`plugin-config.json`、`skill-config.json`、`argv.json`）无 `encryptedKey` / `dbKey` / `safeStorage` 字段。
- 钥匙串存在 `Trae CN Safe Storage`（account `Trae CN`、`Trae CN Key`），这是 Electron `safeStorage`（Chromium 加密 cookie/密码）用的条目，**没有证据表明它就是 SQLCipher 密钥**。
- `libharness.dylib` 只有 SQLCipher 实现，没有明文口令常量；密钥必须在运行时由应用注入或派生。
- `~/.trae-cn/trae-jwt-token` 是登录态 JWT，不是数据库密钥，且使用它属于需要登录态的方向，越界。

结论：**不破解/不逆向密钥派生逻辑就无法读取**。按用户边界（不暴力破解、不改二进制、不绕过签名），在此停下，卡点为「SQLCipher 密钥来源」。

### 4. 日志与其它明文来源：没有可换算的 token 数字

- `cn_session_usage_tail` 是 UI 刷新事件，params 仅 `{action, session_id, user_message_id, agent_message_id, source}`，**没有 token 数值**，不是用量标量。
- `window*/renderer*.log` 中带 token 字样的行绝大部分是聊天文本（含 `[ASSISTANT-DEBUG]`），未找到 `"prompt_tokens":<数字>` / `"totalTokens":<数字>` 形式的数值。
- `Modular/ai_agent-*.alaudalog`（34MB）中 `token_usage` / `prompt_tokens` / `completion_tokens` 命中为 0。
- `aha_log` 命中均为性能日志，无用量。
- `~/.trae-cn/hub_event_cache` 仍只有 `TraeCode/<hub>/<task>.jsonl` 一个文件、一条 `token_usage`（输入 202,133 / 输出 13,010）。

结论：**日志不是可用的 token 来源**；当前唯一明文来源仍是 hub 事件缓存中的 `token_usage`。

### 5. 可行性分类

| 路线 | 判断 | 依据 |
| --- | --- | --- |
| hub_event_cache 明文事件 | 可行且值得做（已实现） | 每条 `token_usage` 带请求级输入/输出，已有适配器与测试 |
| 客户端用量页/账单导出 → 本地导入 | 可行且值得做（本次实施） | 用户可手动导出 CSV/JSON，不依赖登录态接口 |
| 解密 `database.db` 拿全量历史 | 不可行（当前边界内） | 缺 SQLCipher 密钥；逆向 key 派生越界 |
| 从日志还原用量 | 不可行 | 无数值型 usage 字段 |

## 实施：新增外部用量文件导入入口

目标：读不了数据库时，用户可以把 Trae 客户端导出的用量（CSV/JSON）导入 TokenBoard，进入同一套聚合/看板。

### 1. 新增 `src/tokenboard/adapters/external.py`

- `ExternalAdapter(BaseAdapter)`：
  - `name = "external"`、`verified = True`、`auto_discover = False`；
  - 构造参数：`paths`、`platform`（默认 `external`，可传 `trae`）、`mapping`（`dict[str, str]`，键为 `UsageRecord` 字段名，值为源列名/JSON 路径）；
  - `discover()` 返回传入的文件（`.csv` / `.json` / `.jsonl`）；
  - CSV 用 `csv.DictReader`；JSON 支持整文件数组、`{"records": [...]}`、单对象；JSONL 逐行；
  - 字段映射：先按 `mapping` 取值，再回落到 `base.py` 的别名表（`extract_usage`）；
  - `ts` 复用 `base.parse_ts`（支持 epoch 秒/毫秒、ISO 字符串）；
  - 缺 `ts` 时用文件 mtime 并 `logger.warning`；缺 model 记 `unknown`；
  - 产出 `UsageRecord`，`dedup_key` 由 `platform + ts + session_id + model + total` 生成，保证重复导入不重复计数。

### 2. CLI 新增子命令（`src/tokenboard/cli.py`）

`tokenboard import <file...> [--map field=source ...] [--platform trae] [--format table|json|html] [--out PATH]`

- `--map` 可重复，例如 `--map input_tokens=prompt_tokens --map ts=created_at`；
- 复用 `summarize()` 与 `render` 输出 HTML/JSON/table；
- HTML 默认输出 `dist/tokenboard-import.html`，不覆盖既有文件；
- 解析失败时输出明确错误，不静默丢弃。

### 3. 测试

新增 `tests/fixtures/import_usage.csv`、`tests/fixtures/import_usage.json`，并在 `tests/test_adapters.py`（或新增 `tests/test_external.py`）覆盖：

- CSV 标准列名自动识别；
- `--map` 自定义列名（含 JSON 嵌套路径）；
- epoch 秒/毫秒/ISO 时间；
- 缺字段、null、0 的区分；
- JSON 数组与 `records` 包装；
- 重复导入去重。

### 4. 验证

- `python -m unittest discover -s tests -v` 全绿；
- 用临时 CSV 跑一次 `tokenboard import ... --format table`，核对总 Token 与输入/输出；
- 用 JSON 跑一次 `--format html --out dist/tokenboard-import.html`，确认生成且旧文件未被覆盖；
- 回归 `tokenboard scan --platform trae`，确认 hub 事件统计不变。

## 文件清单

- 新增：`src/tokenboard/adapters/external.py`
- 修改：`src/tokenboard/cli.py`（新增 `import` 子命令）
- 修改：`src/tokenboard/adapters/__init__.py`（如需要导出）
- 新增：`tests/fixtures/import_usage.csv`、`tests/fixtures/import_usage.json`
- 修改：`tests/test_adapters.py` 或新增 `tests/test_external.py`
- 修改：`README.md`（补一行导入用法）

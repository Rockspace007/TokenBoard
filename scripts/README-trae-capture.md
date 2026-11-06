# Trae 用量页抓取（可选脚本）

`scripts/trae_capture.py` 用**真实浏览器会话**打开 Trae 用量页，只监听页面自身发出的
响应并原样落盘，然后调用已有的 `tokenboard import` 生成看板。

它**不会**读取、复制或复用 Trae 客户端里的 JWT / token，也不会调用任何需要手工塞 token
的私有接口。登录由你本人在弹出的浏览器里完成，会话保存在本地 profile 目录里。

## 前置条件

- Python 3.10+
- 可选依赖 Playwright（核心看板不需要）：

```bash
pip install -e '.[capture]'
playwright install chromium
```

没装时脚本会直接报错并打印上面两条命令，不会静默失败：

```
[trae-capture][ERROR] 未安装 Playwright，无法启动真实浏览器会话。
```

如果本机已有 Chromium / Chrome，不想再下载 Playwright 自带浏览器，可以复用：

```bash
python3 scripts/trae_capture.py --browser-path "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

（也可用环境变量 `TRAE_BROWSER_PATH` 设置。）

## 首次登录

```bash
python3 scripts/trae_capture.py --login
```

会打开一个非无头 Chromium，profile 存在 `~/.tokenboard/trae-browser`。在窗口里完成
Trae 登录（含验证码），看到用量页后**直接关闭浏览器窗口**，脚本即退出。之后日常抓取
复用这个 profile，不需要再登录。

若默认地址不准，可显式指定：

```bash
python3 scripts/trae_capture.py --login --url https://www.trae.cn/account/usage
```

默认地址可用环境变量 `TRAE_USAGE_URL` 覆盖。

## 日常一键

```bash
python3 scripts/trae_capture.py
```

流程：

1. 用持久化 profile 打开用量页，等待 `--wait` 秒（默认 12）或你手动关闭窗口；
2. 只接收同源、URL 命中用量关键词（`usage` / `quota` / `token` / `bill` /
   `consumption` / `statistic` / `credit`）的响应；
3. 原始响应写到 `~/.tokenboard/trae-capture/<时间戳>/raw/`，清单写同目录
   `manifest.json`（文件权限 0600，目录 0700）；
4. 默认把候选文件交给 `tokenboard import ... --platform trae --format html`，
   输出 `dist/tokenboard-trae.html`。

常用参数：

```bash
# 只看抓到了什么，不导入
python3 scripts/trae_capture.py --dump

# 页面加载慢 / 需要手动点开用量页签
python3 scripts/trae_capture.py --wait 30

# 接口路径不含默认关键词时追加匹配片段
python3 scripts/trae_capture.py --match api/usage

# 落盘前遮盖会话标题、工作空间路径等隐私字段
python3 scripts/trae_capture.py --redact

# 字段名与通用别名不同时，把映射直接传给 import
python3 scripts/trae_capture.py \
  --records data.items \
  --map ts=createdAt \
  --map input_tokens=usage.promptTokens \
  --map output_tokens=usage.completionTokens \
  --map session_id=session.id
```

`--dump` 会打印每个响应的状态码、大小、URL 与字段名，并给出清单路径。原始响应始终
保留，导入失败也能用 `tokenboard import <raw文件>` 重跑。

## 失败排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `[trae-capture][ERROR] 未安装 Playwright` | 可选依赖缺失 | `pip install -e '.[capture]'` + `playwright install chromium` |
| `Executable doesn't exist ... Playwright was just installed or updated` | 浏览器二进制缺失或版本不匹配 | 重新 `playwright install chromium`；或用 `--browser-path` 指向本机已有的 Chromium / Chrome |
| 页面停在登录页 / `login_suspected: true` | 登录态失效 | 重新执行 `--login` |
| `没有监听同名源下的任何候选响应` | URL 不对、未触发用量请求，或关键词未命中 | 用 `--url` 指向实际页面；`--wait 30` 并在等待期间点开用量页签；用 `--match` 追加路径片段 |
| `抓到 N 个响应，但没有一个像用量数据` | 页面改版或接口结构变化 | `--dump` 看 `shape`/字段名；按新字段传 `--map`，必要时 `--records` 指定记录数组 |
| 导入返回非 0 / 记录为空 | 字段映射不匹配 | 保留的 raw 文件可反复 `tokenboard import` 调试；先 `--dump` 再补 `--map` |
| 浏览器打不开页面 | 网络 / 证书 / URL 错误 | 报错会带上原始异常；先 `--login` 手动确认页面可访问 |

所有失败都会保留 `manifest.json` 与 `raw/`，便于定位；不会删除或覆盖历史抓取目录
（每次运行使用新的时间戳目录）。

## 隐私

用量响应可能带会话标题、工作空间路径、账号标识。脚本默认只提示风险，原始文件落在本机
`~/.tokenboard`（0600）。分享前请：

```bash
python3 scripts/trae_capture.py --redact
```

`--redact` 只遮盖标题、路径、邮箱、昵称、工作空间等键（精确键名匹配），保留
`input_tokens` / `total_tokens` 等用量字段，因此不影响导入和去重。

## 边界

- 不读取 `~/.trae-cn` 下的 JWT / token 文件；
- 不调用需要登录态或私有签名的远端接口，只有浏览器自己发出的请求；
- 不修改 Trae 客户端文件；
- Playwright 只是可选依赖，`dependencies = []` 不变。

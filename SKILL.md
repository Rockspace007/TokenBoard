---
name: tokenboard
description: 生成多平台 LLM Token 消耗看板（绿色系主题 + 模型厂商品牌色，单文件离线且可交互的 HTML）。扫描 WorkBuddy / Claude Code / Codex / Trae / OpenCode 等本机会话日志，输出 KPI、模型对比、每日趋势、工作空间→会话→请求三级下钻、0-24 时分布、单次请求大小分布、日活热力图。周期胶囊与日期范围可在页面内直接切换重算。当用户想查看 token 用量、消耗统计、成本审计、跨平台或跨模型对比时使用，例如「看看我的 token 用量」「生成本周消耗看板」「对比各平台用量」「token 审计」。
---

# TokenBoard · 多平台 Token 消耗看板

把本机会话日志里的**请求级真实 usage** 变成一张单文件离线看板。绿色系是 UI 框架，
模型厂商品牌色只用于数据系列；数据不出本机、不依赖任何第三方包。
浅色（白底荧光绿）为默认主题，深色「暗夜玻璃」可在页面右上角一键切换。

## 执行步骤

1. **确认核心包**：本 Skill 与 agent tool 版共享同一套代码。检查 `<skill目录>/src/tokenboard/__init__.py`
   是否存在；不存在说明安装不完整，重新安装整个包（见文末「安装」）。
2. **选择 Python**：优先用平台托管的 Python；否则用 `python3`（Windows 为 `python`）。要求 **3.10+**，
   仅标准库，无需 pip install。
3. **生成看板**（用绝对路径调用）：

   ```bash
   python <skill目录>/scripts/gen_dashboard.py --out <工作区>/tokenboard.html
   ```

   常用可选参数：

   | 参数 | 作用 |
   |---|---|
   | `--platform workbuddy` | 只扫指定平台，可重复；不传则扫所有「已验证」平台 |
   | `--path <目录或文件>` | 扫描自定义日志，走通用适配器（新平台接入先配 `probe`） |
   | `--since 7d` / `--until 2026-11-05` | 时间窗，支持 `YYYY-MM-DD` 与 `Nd` 相对天数；页面内仍可切换周期 |
   | `--theme dark\|light` | light=白底荧光绿（默认）/ dark=暗夜玻璃，页面内也可切换 |
   | `--prices <json>` | 自定义价格表，格式见 `docs/CONTRACT.md` |
   | `--format json\|table` | 输出结构化数据而非 HTML，便于你口头汇报 |
   | `--title "<标题>"` | 自定义看板标题 |

4. **展示结果**：用文件展示工具打开生成的 HTML，并口头汇报关键数字——合计 Token、
   日均、请求轮次、会话数、输入/输出比、缓存命中率、预估金额、主力模型与占比。
5. **说明口径**：金额是按牌价的**粗略预估**，不是账单；不同套餐单价请改 `--prices`。

## 页面交互（生成的 HTML 可直接点击）

- **周期胶囊 / 日期范围**：页面顶部 `1 天 / 3 天 / 近 7 天 / 近 30 天 / 总量` 与起止日期、
  「指定日」日历**真切换**——请求级明细已嵌入页面，JS 端按同一口径重新聚合，全部指标与图表重算。
  **默认聚焦「1 天」**；扫描仍是全历史、明细全量嵌入，切到近 30 天或总量不会丢数据。
- **三级下钻**：点「工作空间活跃分布」里的行 → 会话列表 → 会话详情（请求散点图可切明细表），
  面包屑可逐级返回。
- **模型聚焦**：点模型名或图例，其余模型在图表中变暗；再点取消。
- **悬浮提示**：曲线、热力格、柱、表格行悬停即看单条明细。
- **3X 切片**：下拉把每天切成 1–8 段看行内近 7 日分布；「深色」按钮切暗夜玻璃主题（记忆偏好）。

## 数据源状态（重要）

看板底部有「数据源状态」表，逐平台标出 **已验证 / 未验证**、本机日志文件数，
以及「**导入状态**」列与每行的「导入」按钮。

> 导入按钮需要 `tokenboard serve` 实时模式（或 `./see.command`）才能真正回读本机日志：
> 点击后服务端单平台重扫并把它并入统计，行内显示「已导入」、状态变「已验证」。
> 双击静态 HTML 打开时按钮会提示改用实时模式，不会假装扫描成功。
> 导入集合只存服务进程内存，重启后需重新导入。

- 只有「已验证」的平台会参与**无参数自动扫描**，避免把配置目录、会话记忆目录当用量日志扫进来。
- 用户明确要求看某个未验证平台时，用 `--platform <name>` 或 `--path <真实目录>` 显式指定。
- 接入新平台第一步永远是：`python <skill目录>/scripts/gen_dashboard.py probe --path <目录>`，
  先看「可完整归一化」的百分比，再决定要不要补适配器，别直接相信 0 条结果。

## 数据与口径说明

- 数据源为各平台本机会话日志（`~/.workbuddy/projects`、`~/.claude/projects`、`~/.codex/sessions` 等）
  中的 usage 字段；子代理日志归属父会话，避免会话数虚高。
- 每条记录归一化为：`ts / platform / workspace / session_id / model / input / output /
  cache_read / cache_write / total`，详见 `docs/CONTRACT.md`。
- 计价按每条请求的**实际缓存命中**：读命中走缓存价、缓存写入按输入价 ×1.25、其余输入走输入价、
  输出走输出价。价格表在 `src/tokenboard/pricing.py`，单位元/百万 token。
- 无法确认 usage 或时间戳的日志行会被**丢弃而不是猜测**，因此统计值可能偏低，但不会凭空造数。

## 注意

- 生成的 HTML 完全离线：不引用 CDN、不发 fetch、不加载外部字体；主题偏好存 localStorage。
- **隐私**：交互版把请求级明细（时间/模型/输入输出/缓存）嵌入 HTML 便于页内下钻，
  分享文件即分享明细日志；对外分享前请确认接受，或改用 `--format json|table` 汇报。
- 所有品牌色都配文字标签，不依赖颜色单独传达信息（WCAG 1.4.1）。
- 不要在汇报里把「未验证」平台说成已支持；本机没有对应日志就是没有验证依据。
- 日志内容可能包含用户自己的会话标题，但看板只输出工作空间/模型/数值，不输出消息正文。

## 安装

包内条目自带 `tokenboard/` 前缀，解压到技能根目录即可，**不要加 --strip-components**：

```bash
# 方式一：打包脚本产物
python scripts/pack_skill.py            # 生成 dist/tokenboard-skill.tgz
mkdir -p ~/.workbuddy/skills
tar -xzf dist/tokenboard-skill.tgz -C ~/.workbuddy/skills

# 方式二：直接 clone 仓库
git clone https://github.com/Rockspace007/TokenBoard.git ~/.workbuddy/skills/tokenboard
```

## 致谢

交互与功能设计部分受 [fuyi-git/token-dashboard](https://github.com/fuyi-git/token-dashboard) 启发；
代码、平台适配器、计价口径与文档均为本项目独立实现，未复制其源代码。

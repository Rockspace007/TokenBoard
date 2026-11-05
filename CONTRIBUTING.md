# 贡献指南

## 原则

1. **零运行时依赖**：新增功能只能用 Python 标准库。构建期依赖（setuptools）不算。
2. **口径唯一**：统计、计价、配色只在一个地方实现；不要在新入口里复制逻辑。
3. **诚实优先**：没用真实日志验证过的平台，不要标 `verified`；解析不了的行丢弃而不是猜。

## 本地开发

```bash
git clone <your-repo-url> && cd tokenboard
export PYTHONPATH="$PWD/src"
python -m unittest discover -s tests -v
python scripts/smoke_mcp.py
python -m tokenboard scan --format table
```

## 新增平台适配器

按 [`docs/ADAPTERS.md`](docs/ADAPTERS.md) 的四步走：
`probe` 探路 → 留 fixture → 写 adapter → 注册并跑测试。

**PR 必须包含**：脱敏 fixture、至少一条单元测试、支持矩阵的一行更新。
只有在你本机的真实日志上跑通，才能把 `verified` / `auto_discover` 改成 `True`。

## 改配色

唯一色源是 `src/tokenboard/brands.py`。改动必须同步：

- `docs/DESIGN_TOKENS.md`
- `src/tokenboard/render.py` 的 CSS 变量映射（如果增删 token）
- Ardot 绿色版设计稿

绿色系只能进 UI 框架；品牌色只能进数据系列，且必须保留文字标签。

## 提交前自检

```bash
python -m compileall -q src
python -m unittest discover -s tests -v
python scripts/smoke_mcp.py
python -m tokenboard --version
```

不要在提交里放：本机绝对路径、用户名、邮箱、API Key、真实会话日志、
`*.html` 生成物、`dist/` 打包产物。CI 会在四个 Python 版本 × 三个系统上复验。

## 提交信息

用简短祈使句，例如 `adapter: 补 Claude Code 缓存字段`、`fix: 缓存命中 clamp 到输入上限`。

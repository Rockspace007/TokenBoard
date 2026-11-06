# -*- coding: utf-8 -*-
"""给**其它 agent 应用**的零依赖编程接口（import 即用）。

这里只对 CLI / MCP / Skill 共用的同一套 ``scan → summarize`` 做薄封装，
保证不管从哪个入口取数，口径都完全一致：

>>> from tokenboard.agent_api import report, usage_records   # doctest: +SKIP
>>> print(report(since="7d"))                                # doctest: +SKIP

设计约定（与主项目一致）：
  * 返回的都是纯 Python dict / str，方便任何 agent 直接序列化或口头汇报；
  * **每次调用都是重新扫描**：读各平台日志源头 → 聚合 → 返回，不落盘、
    不缓存、没有需要清理的本地数据库；
  * 只读 usage / 时间戳 / 模型名 / 会话 ID / 工作空间目录名，不碰消息正文。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .aggregate import Summary, summarize
from .cli import parse_date, window_days, window_label
from .models import UsageRecord
from .registry import scan
from .render import render_html

__all__ = (
    "platforms",
    "usage_records",
    "usage_summary",
    "summarize_records",
    "summary_json_text",
    "report",
    "render_board",
)


# ----------------------------------------------------------------------
# 底层封装
# ----------------------------------------------------------------------
def platforms() -> list[dict[str, Any]]:
    """各平台适配器在本机的数据源状态（含默认路径与 file_count）。"""
    from .registry import all_adapters

    return [adapter.status().to_dict() for adapter in all_adapters()]


def _coerce_day(value: Any) -> int | None:
    """Unix 秒原样透传；字符串支持 ``7d`` / ``YYYY-MM-DD``（与 CLI 同一解析）。"""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return parse_date(str(value))


def _scan(
    platforms_: Sequence[str] | None,
    paths: Sequence[str | Path] | None,
    since: Any,
    until: Any,
):
    return scan(
        platforms=list(platforms_) if platforms_ is not None else None,
        paths=[str(p) for p in paths] if paths is not None else None,
        since=_coerce_day(since),
        until=_coerce_day(until),
    )


def summarize_records(records: Sequence[UsageRecord], prices: dict | None = None) -> Summary:
    """把（可能来自任何来源的）请求级记录聚合为 Summary；供测试 / 进阶用法。"""
    return summarize(records, prices)


# ----------------------------------------------------------------------
# 高层接口：任何 agent 都可以直接 import 使用
# ----------------------------------------------------------------------
def usage_records(
    platforms: Sequence[str] | None = None,
    paths: Sequence[str | Path] | None = None,
    since: Any = None,
    until: Any = None,
) -> list[dict[str, Any]]:
    """请求级 usage 明细（每条 = 一次模型请求）。

    返回字段见 docs/CONTRACT.md 的 UsageRecord：ts / platform / workspace /
    session_id / model / input_tokens / output_tokens / cache_read_tokens /
    cache_write_tokens / total_tokens / dedup_key ...
    """
    return [r.to_dict() for r in _scan(platforms, paths, since, until).records]


def usage_summary(
    platforms: Sequence[str] | None = None,
    paths: Sequence[str | Path] | None = None,
    since: Any = None,
    until: Any = None,
    prices: dict | None = None,
) -> dict[str, Any]:
    """聚合结果（KPI / 模型 / 平台 / 工作空间 / 会话 / 日趋势 / 分布）+ 数据源状态。"""
    result = _scan(platforms, paths, since, until)
    summary = summarize(result.records, prices)
    payload = summary.to_dict()
    payload["sources"] = [s.to_dict() for s in result.statuses]
    payload["errors"] = list(result.errors)
    payload["window"] = {
        "label": window_label(since=_coerce_day(since)),
        "since": since,
        "until": until,
    }
    return payload


def summary_json_text(
    platforms: Sequence[str] | None = None,
    paths: Sequence[str | Path] | None = None,
    since: Any = None,
    until: Any = None,
    prices: dict | None = None,
) -> str:
    """与 ``tokenboard scan --format json`` 完全一致的稳定 JSON 文本。"""
    import json as _json

    from .render import summary_json

    result = _scan(platforms, paths, since, until)
    summary = summarize(result.records, prices)
    return summary_json(summary, result.statuses)


def report(
    platforms: Sequence[str] | None = None,
    paths: Sequence[str | Path] | None = None,
    since: Any = None,
    until: Any = None,
    prices: dict | None = None,
) -> str:
    """中文 Markdown 简报，适合 agent 直接放进对话 / 通知 / 卡片。"""
    result = _scan(platforms, paths, since, until)
    if result.errors:
        prefix = "⚠️ 数据源警告：" + "；".join(result.errors) + "\n\n"
    else:
        prefix = ""
    summary = summarize(result.records, prices)
    if not summary.records:
        return prefix + "本窗口内没有扫描到任何请求级 usage 记录。"

    k = summary.kpi()
    top = summary.models[:5]
    model_lines = "\n".join(
        f"  - {m}：{summary.by_model[m]['tokens']:,} tokens × "
        f"{summary.by_model[m]['requests']} 次"
        for m in top
    )
    return (
        f"{prefix}## Token 用量简报（{window_label(_coerce_day(since))}）\n"
        f"- 合计 **{summary.total_tokens:,}** tokens / {k['requests']:,} 次请求，"
        f"覆盖 {k['workspaces']} 个工作空间、{k['sessions']:,} 个会话、"
        f"有数据 {k['active_days']} 天（日均 {k['daily_average']:,.0f}）\n"
        f"- 预估金额 **¥{k['estimated_cost_cny']:.2f}**"
        f"（折合 ¥{k['price_per_million_cny']:.2f} / 百万 tokens）\n"
        f"- 缓存命中率 {k['cache_hit_rate']:.1f}%"
        f"（缓存明细不可算的记录 {k['cache_unknown_records']} 条）\n"
        f"- 输入/输出比 {k['input_output_ratio']:.2f} : 1\n"
        f"- 主力模型：{model_lines}"
    )


def render_board(
    platforms: Sequence[str] | None = None,
    paths: Sequence[str | Path] | None = None,
    since: Any = None,
    until: Any = None,
    prices: dict | None = None,
    out: str | Path = "tokenboard.html",
    theme: str = "light",
    title: str = "TokenBoard · 消耗洞察",
    open_browser: bool = False,
) -> dict[str, Any]:
    """生成单文件离线 HTML 看板，返回文件路径与关键数字。

    ``open_browser=True`` 时写完直接用浏览器打开（agent 环境可关掉）。
    """
    from .pricing import load_prices

    out_path = Path(out).expanduser().resolve()
    if out_path.suffix.lower() not in (".html", ".htm"):
        raise ValueError(f"输出必须是 .html 文件，收到 {out_path.suffix!r}")

    since_ts = _coerce_day(since, "since")
    until_ts = _coerce_day(until, "until")
    result = _scan(platforms, paths, since_ts, until_ts)
    if prices is None:
        price_table = None
    elif isinstance(prices, dict):
        price_table = prices
    else:
        price_table = load_prices(prices)
    summary = summarize(result.records, price_table)
    label = window_label(since_ts)
    html = render_html(
        summary,
        result.records,
        result.statuses,
        theme_name=theme,
        title=title,
        window_label=till_label,
        window_days=window_days(since_ts),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    if open_browser:
        import webbrowser

        webbrowser.open(out_path.as_uri())
    return {
        "path": str(out_path),
        "records": summary.records,
        "kpi": summary.kpi(),
        "models": summary.models,
        "sources": [s.to_dict() for s in result.statuses],
        "errors": list(result.errors),
    }

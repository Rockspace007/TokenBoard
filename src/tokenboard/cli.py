# -*- coding: utf-8 -*-
"""TokenBoard 命令行入口（agent tool 版的「CLI」半侧）。

常用：
    python -m tokenboard                         # 扫描全部平台，生成 tokenboard.html
    python -m tokenboard scan --platform workbuddy --since 7d --out today.html
    python -m tokenboard scan --path ./logs --format json
    python -m tokenboard platforms              # 看哪些平台本机有数据
    python -m tokenboard probe --path ./logs    # 新平台接入前的字段探路
    python -m tokenboard serve-mcp              # 启动 MCP stdio server
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

from . import __version__
from .aggregate import summarize
from .brands import BRAND_COLORS, THEMES
from .pricing import load_prices
from .registry import all_adapters, names, scan
from .render import render_html, summary_json


def parse_date(text: str) -> int:
    """支持 ``YYYY-MM-DD``、``YYYY-MM-DD HH:MM`` 与相对天数 ``7d``。"""
    text = (text or "").strip()
    if text.endswith("d") and text[:-1].isdigit():
        return int((datetime.now() - timedelta(days=int(text[:-1]))).timestamp())
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(datetime.strptime(text, fmt).timestamp())
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"无法解析日期 {text!r}；用 YYYY-MM-DD 或 7d")


def window_label(since: int | None) -> str:
    """把 --since 归纳成看板顶部的周期标签；无 --since 时默认近 30 天。"""
    if since is None:
        return "近 30 天"
    days = round((datetime.now().timestamp() - since) / 86400)
    if 0 <= days <= 365:
        return "1 天" if days <= 1 else f"近 {days} 天"
    return "自定义窗口"


def window_days(since: int | None) -> int | None:
    """窗口覆盖的自然天数；自定义绝对日期返回 None（无法断言空窗）。"""
    if since is None:
        return 30
    days = round((datetime.now().timestamp() - since) / 86400)
    return days if 0 <= days <= 365 else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tokenboard",
        description="多平台 LLM Token 消耗看板（零第三方依赖、数据不出本机）",
    )
    parser.add_argument("--version", action="version", version=f"tokenboard {__version__}")
    sub = parser.add_subparsers(dest="command")

    s = sub.add_parser("scan", help="扫描日志并输出看板 / JSON / 表格")
    s.add_argument("--platform", action="append", help=f"只扫指定平台，可重复；可选 {', '.join(names())}")
    s.add_argument("--path", action="append", help="自定义日志目录或文件，给定后只走通用适配器")
    s.add_argument("--since", type=parse_date, help="起始时间，YYYY-MM-DD 或 7d")
    s.add_argument("--until", type=parse_date, help="结束时间（不含），YYYY-MM-DD")
    s.add_argument("--out", help="输出文件路径；默认 html 写 tokenboard.html，其余写 stdout")
    s.add_argument("--format", choices=("html", "json", "table"), default="html")
    s.add_argument("--theme", choices=("dark", "light"), default="light")
    s.add_argument("--prices", help="自定义价格表 JSON：{模型前缀: [输入, 输出, 缓存读取]}")
    s.add_argument("--title", default="TokenBoard · 消耗洞察")
    s.add_argument("--window-note", default="", help="写在结论条上的数据覆盖提示")

    sub.add_parser("platforms", help="列出平台适配器与本机动静状态")
    sub.add_parser("brands", help="列出模型厂商品牌色映射")
    pr = sub.add_parser("probe", help="探测自定义日志的字段命中率（新平台接入第一步）")
    pr.add_argument("--path", action="append", required=True)
    sub.add_parser("serve-mcp", help="启动 MCP stdio server")
    return parser


def _table(summary, result) -> str:
    k = summary.kpi()
    lines = [
        f"TokenBoard {__version__}  |  记录 {k['requests']:,} 条  |  平台 {len(summary.platforms)} 个",
        "-" * 62,
        f"合计 Token      {summary.total_tokens:>16,}",
        f"日均            {summary.daily_average:>16,.1f}",
        f"会话 / 工作空间 {k['sessions']:>8,} / {k['workspaces']:<6}",
        f"输入 / 输出比   {k['input_output_ratio']:>16.2f} : 1",
        f"缓存命中率      {k['cache_hit_rate']:>15.2f}%",
        f"预估金额        ¥{k['estimated_cost_cny']:>15.2f}",
        f"折合单价        ¥{k['price_per_million_cny']:>13.2f} / 百万",
        "-" * 62,
        "模型：",
    ]
    for m in summary.models[:10]:
        v = summary.by_model[m]
        lines.append(f"  {m:<28} {v['tokens']:>14,}  ¥{v['cost']:.2f}")
    lines.append("平台：")
    for p in summary.platforms:
        lines.append(f"  {p:<28} {summary.by_platform[p]['tokens']:>14,}")
    if result.errors:
        lines.append("警告：" + "; ".join(result.errors))
    return "\n".join(lines)


def cmd_scan(args: argparse.Namespace) -> int:
    result = scan(
        platforms=args.platform,
        paths=args.path,
        since=args.since,
        until=args.until,
    )
    for error in result.errors:
        print(f"[warn] {error}", file=sys.stderr)
    if not result.records:
        print(
            "[warn] 未扫描到任何请求级记录。用 `tokenboard platforms` 检查数据源，"
            "或用 `--path` 指定日志目录。仍会输出一张空看板。",
            file=sys.stderr,
        )

    prices = load_prices(args.prices)
    summary = summarize(result.records, prices)
    if args.format == "json":
        text = summary_json(summary, result.statuses)
    elif args.format == "table":
        text = _table(summary, result)
    else:
        label = window_label(args.since)
        note = args.window_note
        if not note:
            expected = window_days(args.since)
            if expected and summary.active_days and summary.active_days < expected:
                note = (f"当前窗口为{label}，实际仅 {summary.active_days} 天有数据 · "
                        "日均按有数据日计算，空窗不计入")
        text = render_html(
            summary, result.records, result.statuses,
            theme_name=args.theme, title=args.title, window_note=note,
            window_label=label,
            window_days=window_days(args.since),
            custom_range=(args.since, args.until)
            if (args.until or (args.since and window_days(args.since) is None)) else None,
            prices=prices,
        )

    out = args.out or ("tokenboard.html" if args.format == "html" else None)
    if out:
        target = Path(out).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"已写入 {target}  |  {summary.records} 条记录  |  {len(target.read_text(encoding='utf-8')):,} 字符", file=sys.stderr)
    else:
        print(text)
    return 0 if not result.errors else 1


def cmd_platforms(_args: argparse.Namespace) -> int:
    for adapter in all_adapters():
        s = adapter.status()
        flag = "已验证" if s.verified else "未验证"
        print(f"{s.name:<14} {s.display_name:<22} 文件 {s.file_count:<5} {flag}")
        for root in s.roots or ("(无默认路径)",):
            print(f"    {root}")
        if s.note:
            print(f"    说明：{s.note}")
    return 0


def cmd_brands(_args: argparse.Namespace) -> int:
    print(f"{'前缀':<14}{'品牌色':<12}{'厂商'}")
    print("-" * 44)
    for key, color in BRAND_COLORS.items():
        print(f"{key:<14}{color:<12}")
    print(f"\n主题令牌：{', '.join(THEMES)}（绿系统一 UI 框架）")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """统计自定义日志里能解析出 usage / 时间戳的比例，用于新平台接入前的探路。"""
    from .adapters.base import extract_model, extract_ts, extract_usage
    from .adapters.generic import GenericAdapter

    adapter = GenericAdapter(roots=[Path(p).expanduser() for p in args.path])
    files = adapter.discover()
    total = usage_ok = ts_ok = both_ok = 0
    models: set[str] = set()
    for path in files[:20]:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for index, raw in enumerate(fh):
                if index >= 500:  # 每个文件最多抽样 500 行，避免大文件卡住
                    break
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                total += 1
                usage = extract_usage(obj)
                ts = extract_ts(obj)
                usage_ok += bool(usage)
                ts_ok += bool(ts)
                if usage and ts:
                    both_ok += 1
                    models.add(extract_model(obj))

    print(f"文件 {len(files)} 个  |  抽样行 {total} 条")
    if not total:
        print("没有读到可解析的 JSON 行。请检查 --path 是否指向 jsonl 日志。")
        return 1
    print(f"usage 字段命中   {usage_ok / total * 100:6.1f}%")
    print(f"时间戳字段命中   {ts_ok / total * 100:6.1f}%")
    print(f"可完整归一化     {both_ok / total * 100:6.1f}%   <- 这个数才是真实覆盖率")
    print(f"识别到的模型     {', '.join(sorted(models)[:12]) or '(无)'}")
    if both_ok / total < 0.3:
        print("命中率偏低：该平台大概率用了私有字段，请按 docs/ADAPTERS.md 补一个适配器。")
    return 0


COMMANDS = {
    "scan": cmd_scan,
    "platforms": cmd_platforms,
    "brands": cmd_brands,
    "probe": cmd_probe,
}


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # 省略子命令时默认走 scan，降低上手成本；
    # 但顶层 --version / --help 必须留给 parser 自己处理，不能被塞进 scan。
    if not raw:
        raw = ["scan"]
    elif raw[0] in ("--version", "-h", "--help"):
        pass
    elif raw[0].startswith("-"):
        raw = ["scan"] + raw
    args = build_parser().parse_args(raw)
    if args.command == "serve-mcp":
        from .mcp_server import serve

        serve()
        return 0
    handler = COMMANDS.get(args.command)
    if handler is None:
        build_parser().print_help()
        return 2
    return handler(args)

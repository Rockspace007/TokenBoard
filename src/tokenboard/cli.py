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
from .registry import ScanResult, all_adapters, names, scan
from .render import render_html, summary_json


def mapping_pair(text: str) -> tuple[str, str]:
    """解析 ``--map FIELD=SOURCE``；FIELD 必须是 UsageRecord 字段名。"""
    from .adapters.external import MAPPING_FIELDS

    field, sep, source = text.partition("=")
    field, source = field.strip(), source.strip()
    if not sep or not field or not source:
        raise argparse.ArgumentTypeError(f"字段映射应为 FIELD=SOURCE，收到 {text!r}")
    if field not in MAPPING_FIELDS:
        raise argparse.ArgumentTypeError(
            f"未知字段 {field!r}；可选：{', '.join(sorted(MAPPING_FIELDS))}"
        )
    return field, source


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
    s.add_argument(
        "--open", dest="open_browser", action="store_true",
        help="写完 HTML 后直接用浏览器打开看板（--format html 时有效）",
    )
    s.add_argument("--format", choices=("html", "json", "table"), default="html")
    s.add_argument("--theme", choices=("dark", "light"), default="light")
    s.add_argument("--prices", help="自定义价格表 JSON：{模型前缀: [输入, 输出, 缓存读取]}")
    s.add_argument("--title", default="TokenBoard · 消耗洞察")
    s.add_argument("--window-note", default="", help="写在结论条上的数据覆盖提示")

    im = sub.add_parser("import", help="导入外部 CSV / JSON 用量文件（字段映射可配）")
    im.add_argument("files", nargs="+", help="CSV / JSON / JSONL 文件或目录")
    im.add_argument(
        "--map", dest="maps", action="append", type=mapping_pair, metavar="FIELD=SOURCE",
        help="字段映射，可重复；如 --map input_tokens=prompt_tokens --map ts=created_at",
    )
    im.add_argument("--platform", default="external", help="记录归属平台，默认 external；导入 Trae 导出可传 trae")
    im.add_argument(
        "--records", metavar="PATH",
        help="JSON 记录数组所在的点分路径（如 data.items）；默认自动探测 records/data/items/usages",
    )
    im.add_argument("--format", choices=("table", "json", "html"), default="table")
    im.add_argument("--out", help="输出文件路径；html 默认 dist/tokenboard-import.html")
    im.add_argument(
        "--open", dest="open_browser", action="store_true",
        help="写完 HTML 后直接用浏览器打开看板（--format html 时有效）",
    )
    im.add_argument("--theme", choices=("dark", "light"), default="light")
    im.add_argument("--prices", help="自定义价格表 JSON")
    im.add_argument("--title", default="TokenBoard · 外部用量导入")
    im.add_argument("--window-note", default="外部用量文件导入 · 非实时扫描")

    sub.add_parser("platforms", help="列出平台适配器与本机动静状态")
    sub.add_parser("brands", help="列出模型厂商品牌色映射")
    pr = sub.add_parser("probe", help="探测自定义日志的字段命中率（新平台接入第一步）")
    pr.add_argument("--path", action="append", required=True)
    sub.add_parser("serve-mcp", help="启动 MCP stdio server")
    sv = sub.add_parser("serve", help="启动本地实时看板：每次刷新都重新扫描本机日志")
    sv.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    sv.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    sv.add_argument("--platform", action="append", help=f"只扫指定平台，可重复；可选 {', '.join(names())}")
    sv.add_argument("--since", type=parse_date, help="起始时间，YYYY-MM-DD 或 7d")
    sv.add_argument("--until", type=parse_date, help="结束时间（不含），YYYY-MM-DD")
    sv.add_argument("--theme", choices=("dark", "light"), default="light")
    sv.add_argument("--title", default="TokenBoard · 消耗洞察")
    sv.add_argument("--prices", help="自定义价格表 JSON：{模型前缀: [输入, 输出, 缓存读取]}")
    sv.add_argument("--open", dest="open_browser", action="store_true",
                   help="启动后立即在浏览器打开看板")
    return parser


def _table(summary, result) -> str:
    k = summary.kpi()
    if k["cache_hit_known"]:
        cache_text = f"{k['cache_hit_rate']:>15.2f}%"
    elif k["cache_unknown_records"]:
        cache_text = f"{'不可算':>14}（缓存字段缺失）"
    else:
        cache_text = f"{0.0:>15.2f}%"
    lines = [
        f"TokenBoard {__version__}  |  记录 {k['requests']:,} 条  |  平台 {len(summary.platforms)} 个",
        "-" * 62,
        f"合计 Token      {summary.total_tokens:>16,}",
        f"日均            {summary.daily_average:>16,.1f}",
        f"会话 / 工作空间 {k['sessions']:>8,} / {k['workspaces']:<6}",
        f"输入 / 输出比   {k['input_output_ratio']:>16.2f} : 1",
        f"缓存命中率      {cache_text}",
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


def _emit(args: argparse.Namespace, result, summary, default_html: str) -> int:
    """scan / import 共用的输出逻辑：JSON、表格或 HTML 看板。"""
    since = getattr(args, "since", None)
    until = getattr(args, "until", None)
    prices = load_prices(getattr(args, "prices", None))
    if args.format == "json":
        text = summary_json(summary, result.statuses)
    elif args.format == "table":
        text = _table(summary, result)
    else:
        label = window_label(since)
        note = getattr(args, "window_note", "")
        if not note:
            expected = window_days(since)
            if expected and summary.active_days and summary.active_days < expected:
                note = (f"当前窗口为{label}，实际仅 {summary.active_days} 天有数据 · "
                        "日均按有数据日计算，空窗不计入")
        text = render_html(
            summary, result.records, result.statuses,
            theme_name=getattr(args, "theme", "light"),
            title=getattr(args, "title", "TokenBoard · 消耗洞察"),
            window_note=note,
            window_label=label,
            window_days=window_days(since),
            custom_range=(since, until)
            if (until or (since and window_days(since) is None)) else None,
            prices=prices,
        )

    out = args.out or (default_html if args.format == "html" else None)
    if out:
        target = Path(out).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"已写入 {target}  |  {summary.records} 条记录  |  {len(text):,} 字符", file=sys.stderr)
        if getattr(args, "open_browser", False) and args.format == "html":
            import webbrowser

            webbrowser.open(target.as_uri())
            print("已在浏览器打开", file=sys.stderr)
    else:
        print(text)
    return 0 if not result.errors else 1


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
    return _emit(args, result, summary, "tokenboard.html")


def cmd_import(args: argparse.Namespace) -> int:
    """导入外部 CSV / JSON 用量文件；字段映射通过 --map 可配。"""
    from .adapters.external import ExternalAdapter

    adapter = ExternalAdapter(
        paths=[Path(p).expanduser() for p in args.files],
        platform=args.platform,
        mapping=dict(args.maps or []),
        records_path=args.records,
    )
    files = adapter.discover()
    if not files:
        print(f"[error] 未找到可导入的 CSV/JSON 文件：{', '.join(args.files)}", file=sys.stderr)
        return 2

    records = list(adapter.iter_all_records())
    result = ScanResult(records=records, statuses=[adapter.status()])
    for error in result.errors:
        print(f"[warn] {error}", file=sys.stderr)
    if not records:
        print("[warn] 文件中没有可归一化的 usage 记录；检查列名或 --map 映射。", file=sys.stderr)

    summary = summarize(records, load_prices(args.prices))
    return _emit(args, result, summary, "dist/tokenboard-import.html")


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
    "import": cmd_import,
    "platforms": cmd_platforms,
    "brands": cmd_brands,
    "probe": cmd_probe,
}


def _force_utf8_streams() -> None:
    """把 stdout / stderr 重配置为 UTF-8。

    Windows 的管道 / 重定向输出默认用 ANSI 代码页（如 cp1252），
    表格与提示里的中文、`¥` 会直接 UnicodeEncodeError。
    在入口处统一重配置：不支持编码的字符降级替换，永不崩。
    StringIO（测试环境）没有 reconfigure，hasattr 挡掉即可。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def cmd_serve(args: argparse.Namespace) -> int:
    """本地实时看板：每收到一次 GET 都重新扫描本机日志并渲染，页面「刷新」即拉取最新数据。"""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    prices = load_prices(args.prices)
    cfg = dict(
        platforms=args.platform, since=args.since, until=args.until,
        theme=args.theme, title=args.title, prices=prices,
    )

    def build_html() -> str:
        result = scan(
            platforms=cfg["platforms"], paths=None,
            since=cfg["since"], until=cfg["until"],
        )
        for error in result.errors:
            print(f"[warn] {error}", file=sys.stderr)
        summary = summarize(result.records, cfg["prices"])
        label = window_label(cfg["since"])
        note = ""
        expected = window_days(cfg["since"])
        if expected and summary.active_days and summary.active_days < expected:
            note = (f"当前窗口为{label}，实际仅 {summary.active_days} 天有数据 · "
                    "日均按有数据日计算，空窗不计入")
        return render_html(
            summary, result.records, result.statuses,
            theme_name=cfg["theme"], title=cfg["title"],
            window_note=note, window_label=label,
            window_days=expected,
            custom_range=(cfg["since"], cfg["until"])
            if (cfg["until"] or (cfg["since"] and window_days(cfg["since"]) is None)) else None,
            prices=cfg["prices"],
        )

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802  (http.server 约定)
            try:
                body = build_html().encode("utf-8")
            except Exception as exc:  # 单页失败不应拖垮服务
                self.send_error(500, f"渲染失败：{exc}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):  # 静默默认访问日志
            return

    srv = ThreadingHTTPServer((args.host, args.port), _Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"TokenBoard 实时看板已启动：{url}", file=sys.stderr)
    print("页面「刷新」按钮会重新扫描本机日志拉取最新数据；按 Ctrl+C 停止。", file=sys.stderr)
    if args.open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。", file=sys.stderr)
    finally:
        srv.server_close()
    return 0


COMMANDS["serve"] = cmd_serve


def main(argv: Sequence[str] | None = None) -> int:
    _force_utf8_streams()
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

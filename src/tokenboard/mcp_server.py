# -*- coding: utf-8 -*-
"""零依赖 MCP Server（stdio / JSON-RPC 2.0）。

MCP 的 stdio 传输是**每行一个 JSON 消息**（不是 LSP 的 Content-Length 头），
所以直接逐行读写 stdin/stdout 即可，无需 mcp / fastmcp 之类的第三方包。

铁律：任何诊断信息只能写 stderr。stdout 多一行日志都会破坏协议流。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .aggregate import summarize
from .brands import BRAND_COLORS, THEMES
from .pricing import load_prices
from .registry import all_adapters, scan
from .render import render_html

PROTOCOL_VERSION = "2024-11-05"

_SCAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "platforms": {"type": "array", "items": {"type": "string"},
                      "description": "只扫描指定平台，如 workbuddy / claude_code / codex / trae / opencode"},
        "paths": {"type": "array", "items": {"type": "string"},
                  "description": "自定义日志目录或文件；给定后忽略 platforms"},
        "since": {"type": "integer", "description": "起始 Unix 秒（含）"},
        "until": {"type": "integer", "description": "结束 Unix 秒（不含）"},
        "prices": {"type": "string", "description": "自定义价格表 JSON 文件路径"},
    },
    "additionalProperties": False,
}

_RENDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **_SCAN_SCHEMA["properties"],
        "out": {"type": "string", "description": "HTML 输出路径，默认当前目录 tokenboard.html"},
        "theme": {"type": "string", "enum": ["dark", "light"], "default": "dark"},
        "title": {"type": "string"},
    },
    "additionalProperties": False,
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "tokenboard_scan",
        "description": "扫描本机各 AI 编程平台的会话日志，返回归一化的 Token 消耗 KPI、模型/平台/工作空间分布与数据源状态。数据不出本机。",
        "inputSchema": _SCAN_SCHEMA,
    },
    {
        "name": "tokenboard_render",
        "description": "扫描并生成单文件离线 HTML 看板，返回文件绝对路径与摘要。绿色系 UI + 模型厂商品牌色数据系列。",
        "inputSchema": _RENDER_SCHEMA,
    },
    {
        "name": "tokenboard_platforms",
        "description": "列出所有平台适配器、默认日志路径、本机文件数与「是否已用真实数据验证」。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tokenboard_brands",
        "description": "返回绿色系主题令牌与模型厂商品牌色映射表，供其它工具复用同一套配色。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _ok(mid: Any, result: dict[str, Any]) -> None:
    _emit({"jsonrpc": "2.0", "id": mid, "result": result})


def _fail(mid: Any, code: int, message: str) -> None:
    _emit({"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}})


def _text(payload: Any) -> dict[str, Any]:
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": body}], "isError": False}


def _error_text(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _do_scan(args: dict[str, Any]):
    """scan 与 render 共用的扫描，保证口径完全一致。"""
    result = scan(
        platforms=args.get("platforms"),
        paths=args.get("paths"),
        since=args.get("since"),
        until=args.get("until"),
    )
    prices = load_prices(args.get("prices"))
    summary = summarize(result.records, prices)
    return result, summary


def _tool_scan(args: dict[str, Any]) -> dict[str, Any]:
    result, summary = _do_scan(args)
    payload = summary.to_dict()
    payload["sources"] = [s.to_dict() for s in result.statuses]
    payload["errors"] = result.errors
    return _text(payload)


def _tool_render(args: dict[str, Any]) -> dict[str, Any]:
    out = Path(args.get("out") or "tokenboard.html").expanduser().resolve()
    # 只写 HTML，避免工具被误用去覆盖任意文件
    if out.suffix.lower() not in (".html", ".htm"):
        return _error_text(f"拒绝写入：输出文件必须是 .html / .htm，收到 {out.suffix!r}")
    result, summary = _do_scan(args)
    html = render_html(
        summary, result.records, result.statuses,
        theme_name=args.get("theme", "light"),
        title=args.get("title", "TokenBoard · 多平台消耗洞察"),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return _text({
        "path": str(out),
        "records": summary.records,
        "kpi": summary.kpi(),
        "models": summary.models,
        "sources": [s.to_dict() for s in result.statuses],
        "errors": result.errors,
    })


def _tool_platforms(_args: dict[str, Any]) -> dict[str, Any]:
    return _text([adapter.status().to_dict() for adapter in all_adapters()])


def _tool_brands(_args: dict[str, Any]) -> dict[str, Any]:
    return _text({
        "themes": {name: tokens for name, tokens in THEMES.items()},
        "brand_colors": BRAND_COLORS,
        "rule": "绿色系仅用于 UI 框架；品牌色仅用于数据系列且必须附文字标签",
    })


DISPATCH = {
    "tokenboard_scan": _tool_scan,
    "tokenboard_render": _tool_render,
    "tokenboard_platforms": _tool_platforms,
    "tokenboard_brands": _tool_brands,
}


def handle(message: dict[str, Any]) -> None:
    method = message.get("method")
    mid = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        _ok(mid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "tokenboard", "version": __version__},
        })
        return
    if method in ("notifications/initialized", "notifications/cancelled"):
        return  # notification 没有 id，绝对不能回复
    if method == "ping":
        _ok(mid, {})
        return
    if method == "tools/list":
        _ok(mid, {"tools": TOOLS})
        return
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = DISPATCH.get(name)
        if handler is None:
            _ok(mid, _error_text(f"未知工具 {name!r}；可用：{', '.join(DISPATCH)}"))
            return
        try:
            _ok(mid, handler(arguments))
        except Exception as exc:  # 工具异常要回给调用方，不能让 server 崩掉
            _ok(mid, _error_text(f"{type(exc).__name__}: {exc}"))
        return
    if mid is not None:
        _fail(mid, -32601, f"Method not found: {method}")


def serve() -> None:
    """阻塞读取 stdin，直到 EOF。可用 Ctrl+D 或关闭管道结束。"""
    print("[tokenboard] MCP stdio server ready", file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            print(f"[tokenboard] 忽略非法 JSON: {line[:80]}", file=sys.stderr)
            continue
        if not isinstance(message, dict):
            continue
        try:
            handle(message)
        except Exception as exc:  # 兜底：任何未捕获异常都不应打断后续消息
            print(f"[tokenboard] handle 异常: {exc}", file=sys.stderr)
            if message.get("id") is not None:
                _fail(message["id"], -32603, str(exc))

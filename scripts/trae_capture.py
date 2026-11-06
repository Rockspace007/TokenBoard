#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Trae 用量页抓取原始响应，并交给 ``tokenboard import`` 生成看板。

设计约束：
  * 不读取、不复制、不复用 Trae 客户端的 JWT / token，也不调用任何私有接口；
  * 使用真实浏览器会话，由用户在弹出的浏览器里自行登录；
  * 只监听用量页自身发出的响应并原样落盘，解析与字段映射全部复用 tokenboard；
  * Playwright 是可选依赖，缺失时明确报错并给出安装命令，不静默失败。

常用：
    python3 scripts/trae_capture.py --login          # 首次：登录一次，profile 会保存会话
    python3 scripts/trae_capture.py                  # 日常：抓取 -> 导入 -> 生成 HTML
    python3 scripts/trae_capture.py --dump           # 只看抓到了什么，不导入
    python3 scripts/trae_capture.py --url <用量页> --wait 25 --redact
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

TOOL_VERSION = "1"
HOME = Path(os.environ.get("TOKENBOARD_HOME") or Path.home() / ".tokenboard")
DEFAULT_PROFILE = HOME / "trae-browser"
DEFAULT_OUTPUT_ROOT = HOME / "trae-capture"
DEFAULT_URL = os.environ.get("TRAE_USAGE_URL", "https://www.trae.cn/account/usage")

# URL 命中关键词：用量页的接口路径通常带这些词
MATCH_KEYWORDS = (
    "usage", "quota", "token", "bill", "consumption", "statistic", "credit",
)
# 判断响应体像不像用量数据（与 tokenboard 的通用别名保持一致）
USAGE_HINT_KEYS = (
    "input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens",
    "inputTokens", "outputTokens", "totalTokens", "promptTokens", "completionTokens",
    "cache_read_tokens", "cache_write_tokens", "cacheReadTokens", "cacheWriteTokens",
    "usage", "tokenUsage", "tokens",
)
# 落盘时要遮盖的隐私字段（精确匹配，避免误伤 total_tokens 之类的用量字段）
REDACT_KEYS = {
    "title", "sessiontitle", "conversationtitle", "workspacename", "workspacepath",
    "path", "filepath", "projectpath", "projectname", "email", "username", "nickname",
    "phone", "ip", "avatar", "workspace",
}
MAX_BODY_BYTES = 8 * 1024 * 1024

PRIVACY_NOTE = (
    "原始响应可能包含会话标题、工作空间路径、账号标识等隐私信息；"
    "默认落在本机 ~/.tokenboard 下（权限 0600），分享前请使用 --redact 或自行脱敏。"
)

INSTALL_HINT = (
    "[trae-capture][ERROR] 未安装 Playwright，无法启动真实浏览器会话。\n"
    "  安装可选依赖：pip install -e '.[capture]'\n"
    "  或手动安装：  pip install playwright && playwright install chromium\n"
    "  核心看板不依赖 Playwright，未安装时只有抓取步骤不可用。"
)


def install_hint() -> str:
    return INSTALL_HINT


# ---------------------------------------------------------------- 纯函数工具

def same_origin(url: str, origin: str) -> bool:
    """两个 URL 是否同源（协议 + 主机 + 端口）。"""
    try:
        a, b = urlsplit(url), urlsplit(origin)
    except ValueError:
        return False
    return (a.scheme, a.netloc) == (b.scheme, b.netloc)


def matches_url(url: str, keywords: list[str] | tuple[str, ...]) -> bool:
    """URL（含 query）是否命中用量关键词。"""
    lowered = url.lower()
    return any(word.lower() in lowered for word in keywords if word)


def looks_like_usage(payload: object, depth: int = 0) -> bool:
    """粗判响应体是否像用量数据：看字段名，不看值。"""
    if depth > 3:
        return False
    if isinstance(payload, list):
        return any(looks_like_usage(item, depth + 1) for item in payload[:5])
    if isinstance(payload, dict):
        if any(key in USAGE_HINT_KEYS for key in payload):
            return True
        return any(
            isinstance(value, (dict, list)) and looks_like_usage(value, depth + 1)
            for value in payload.values()
        )
    return False


def redact_payload(node: object) -> object:
    """递归遮盖隐私字段；用量字段保持原样。"""
    if isinstance(node, dict):
        return {
            key: ("<redacted>" if str(key).lower() in REDACT_KEYS else redact_payload(value))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [redact_payload(item) for item in node]
    return node


def top_level_shape(payload: object) -> dict:
    """给出响应的结构摘要，便于 --dump 肉眼判断是否改版。"""
    if isinstance(payload, list):
        first = payload[0] if payload else None
        return {
            "type": "list",
            "count": len(payload),
            "item_keys": sorted(first.keys())[:24] if isinstance(first, dict) else [],
        }
    if isinstance(payload, dict):
        return {"type": "object", "keys": sorted(str(k) for k in payload.keys())[:24]}
    return {"type": type(payload).__name__}


def build_manifest(
    *,
    mode: str,
    url: str,
    final_url: str,
    profile: Path,
    keywords: list[str],
    started_at: str,
    finished_at: str,
    responses: list[dict],
    candidates: list[str],
    login_suspected: bool,
    errors: list[str],
    redacted: bool,
) -> dict:
    """生成可复现的抓取清单（不含任何响应正文）。"""
    return {
        "tool": "trae_capture",
        "version": TOOL_VERSION,
        "mode": mode,
        "started_at": started_at,
        "finished_at": finished_at,
        "url": url,
        "final_url": final_url,
        "profile": str(profile),
        "match_keywords": keywords,
        "login_suspected": login_suspected,
        "redacted": redacted,
        "privacy_note": PRIVACY_NOTE,
        "response_count": len(responses),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "responses": responses,
        "errors": errors,
    }


def _slug(url: str, index: int) -> str:
    """把 URL 路径变成安全短名，用于 raw 文件名。"""
    path = urlsplit(url).path or "/"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path).strip("-") or "root"
    stem = stem[-48:].strip("-")
    return f"{index:03d}_{stem}"


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _log(level: str, message: str) -> None:
    print(f"[trae-capture][{level}] {message}", file=sys.stderr)


def _install_playwright_or_none():
    """延迟导入 Playwright；返回 ``sync_playwright`` 或 ``None``。"""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        return None
    return sync_playwright


def _load_tokenboard_main():
    """复用已安装的 tokenboard；在源码仓库里直接运行也能回退到 src/。"""
    try:
        from tokenboard.cli import main as cli_main
        return cli_main
    except ImportError:
        src = Path(__file__).resolve().parents[1] / "src"
        if (src / "tokenboard").is_dir():
            sys.path.insert(0, str(src))
            try:
                from tokenboard.cli import main as cli_main
                return cli_main
            except ImportError:
                pass
    return None


# ---------------------------------------------------------------- 浏览器流程

def _launch_options(headless: bool, browser_path: str) -> dict:
    """浏览器启动参数；--browser-path 可复用本机已有的 Chromium/Chrome。"""
    options: dict = {"headless": headless}
    if browser_path:
        options["executable_path"] = browser_path
    return options


def run_login(profile: Path, url: str, browser_path: str = "") -> int:
    """打开持久化浏览器让用户自行登录，关闭浏览器后结束。"""
    sync_playwright = _install_playwright_or_none()
    if sync_playwright is None:
        print(install_hint(), file=sys.stderr)
        return 2

    profile.mkdir(parents=True, exist_ok=True)
    os.chmod(profile, 0o700)
    _log("INFO", f"打开浏览器，profile：{profile}")
    _log("INFO", "请在浏览器里完成 Trae 登录（含验证码），看到用量页后直接关闭浏览器窗口。")

    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(profile), **_launch_options(False, browser_path)
            )
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:  # 登录页打不开也允许用户手动导航
                _log("WARN", f"打开 {url} 失败：{exc}；可手动在地址栏输入用量页地址")
            while True:
                pages = [p for p in context.pages if not p.is_closed()]
                if not pages:
                    break
                try:
                    pages[-1].wait_for_timeout(500)
                except Exception:
                    break
            try:
                context.close()
            except Exception:
                pass
    except KeyboardInterrupt:
        _log("WARN", "登录流程被中断；已写入 profile 的会话仍然有效。")

    _log("INFO", "登录窗口已关闭。日常抓取可直接运行：python3 scripts/trae_capture.py")
    return 0


def _read_args_defaults(args: argparse.Namespace) -> tuple[Path, Path, list[str]]:
    profile = Path(os.path.expanduser(args.profile)).resolve()
    out_root = Path(os.path.expanduser(args.output_root)).resolve()
    keywords = list(MATCH_KEYWORDS) + list(args.match or [])
    return profile, out_root, keywords


def run_capture(args: argparse.Namespace) -> int:
    sync_playwright = _install_playwright_or_none()
    if sync_playwright is None:
        print(install_hint(), file=sys.stderr)
        return 2

    profile, out_root, keywords = _read_args_defaults(args)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out).expanduser().resolve() if args.out else out_root / stamp
    raw_dir = out_dir / "raw"
    for directory in (out_dir, raw_dir):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)

    url = args.url
    origin = url
    started_at, finished_at = _iso_now(), ""
    responses: list[dict] = []
    candidates: list[str] = []
    errors: list[str] = []
    login_suspected = False
    final_url = ""
    redacted = bool(args.redact)

    def handle_response(response) -> None:
        req_url = response.url
        if not same_origin(req_url, origin) or not matches_url(req_url, keywords):
            return
        try:
            content_type = response.headers.get("content-type", "")
        except Exception:
            content_type = ""
        try:
            body = response.body()
        except Exception as exc:
            responses.append({
                "url": req_url, "status": response.status, "content_type": content_type,
                "bytes": 0, "saved": None, "error": f"读取响应体失败：{exc}",
            })
            return

        index = len(responses) + 1
        truncated = len(body) > MAX_BODY_BYTES
        raw_bytes = body[:MAX_BODY_BYTES]
        text = raw_bytes.decode("utf-8", errors="replace")
        payload = None
        parse_error = ""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
        if redacted and payload is not None:
            payload = redact_payload(payload)
            text = json.dumps(payload, ensure_ascii=False)
            raw_bytes = text.encode("utf-8")

        if payload is None and "json" not in content_type.lower():
            responses.append({
                "url": req_url, "status": response.status, "content_type": content_type,
                "bytes": len(body), "saved": None, "skipped": "非 JSON 响应，未落盘",
            })
            return

        suffix = ".json" if payload is not None else ".txt"
        raw_path = raw_dir / (_slug(req_url, index) + suffix)
        raw_path.write_bytes(raw_bytes)
        os.chmod(raw_path, 0o600)

        entry = {
            "file": str(raw_path),
            "url": req_url,
            "status": response.status,
            "content_type": content_type,
            "bytes": len(body),
            "truncated": truncated,
            "json": payload is not None,
            "parse_error": parse_error,
            "shape": top_level_shape(payload) if payload is not None else {},
            "usage_like": bool(payload is not None and looks_like_usage(payload)),
        }
        responses.append(entry)
        if entry["usage_like"]:
            candidates.append(str(raw_path))

    page = None
    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(profile), **_launch_options(bool(args.headless), args.browser_path)
            )

            def attach(target) -> None:
                target.on("response", handle_response)

            for existing in context.pages:
                attach(existing)
            context.on("page", attach)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=args.timeout * 1000)
            except Exception as exc:
                errors.append(f"打开用量页失败：{exc}")
                _log("ERROR", f"打开 {url} 失败：{exc}（检查 URL / 网络 / 证书）")
            else:
                deadline = time.time() + args.wait
                while time.time() < deadline:
                    pages = [p for p in context.pages if not p.is_closed()]
                    if not pages:
                        break
                    try:
                        pages[-1].wait_for_timeout(400)
                    except Exception:
                        break
            try:
                final_url = page.url if page is not None else ""
            except Exception:
                final_url = ""
            if page is not None and any(
                token in final_url.lower() for token in ("login", "signin", "passport")
            ):
                login_suspected = True
                errors.append("页面跳转到了登录页，登录态可能已失效；先运行 --login 重新登录")
                _log("ERROR", "疑似登录态失效：页面最终停在登录页；先运行 --login")
            try:
                context.close()
            except Exception:
                pass
    except KeyboardInterrupt:
        _log("WARN", "抓取被中断，已落盘的原始响应仍会保留")
    except Exception as exc:
        errors.append(f"浏览器会话异常：{exc}")
        _log("ERROR", f"浏览器会话异常：{exc}")
        if "Executable doesn't exist" in str(exc):
            _log("ERROR", "浏览器二进制缺失/版本不匹配：运行 playwright install chromium，"
                          "或用 --browser-path 指向本机已有的 Chromium / Chrome")
    finally:
        finished_at = _iso_now()

    manifest = build_manifest(
        mode="capture", url=url, final_url=final_url, profile=profile,
        keywords=keywords, started_at=started_at, finished_at=finished_at,
        responses=responses, candidates=candidates,
        login_suspected=login_suspected, errors=errors, redacted=redacted,
    )
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(manifest_path, 0o600)

    _log("WARN", PRIVACY_NOTE)
    if args.dump:
        _dump(manifest_path, responses, candidates, errors)

    if not responses:
        _log("ERROR", "没有监听同名源下的任何候选响应。可能原因：")
        _log("ERROR", "  1) 登录态失效（先 --login）；2) 用量页地址不对（用 --url 指向实际页面）；")
        _log("ERROR", "  3) 页面没有自动请求用量接口（用 --wait 30 并在等待期间点开用量/账单页签）；")
        _log("ERROR", "  4) 接口路径换了关键词（用 --match 追加实际路径片段，例如 --match api/usage）")
        _log("ERROR", f"原始清单已保留：{manifest_path}")
        return 1
    if not candidates:
        _log("ERROR", f"抓到 {len(responses)} 个响应，但没有一个像用量数据（页面可能改版）。")
        _log("ERROR", f"先用 --dump 查看结构：{manifest_path}")
        _log("ERROR", "如果确认字段改名，可用 --map FIELD=SOURCE 把字段映射到 tokenboard。")
        return 1

    _log("INFO", f"抓到 {len(candidates)} 个候选响应，清单：{manifest_path}")
    if args.dump:
        return 0

    cli_main = _load_tokenboard_main()
    if cli_main is None:
        _log("ERROR", "找不到 tokenboard；先执行 pip install -e . 或在仓库根目录运行本脚本")
        _log("INFO", f"原始响应已保留：{raw_dir}")
        return 2

    argv = ["import", *candidates, "--platform", args.platform, "--format", args.format,
            "--title", "TokenBoard · Trae 用量页",
            "--window-note", "Trae 用量页抓取 · 原始响应快照"]
    if args.format == "html":
        argv += ["--out", str(Path(args.dashboard).expanduser())]
    if args.records:
        argv += ["--records", args.records]
    for pair in args.maps or []:
        argv += ["--map", pair]
    exit_code = cli_main(argv)
    if exit_code != 0:
        _log("ERROR", f"导入返回 {exit_code}；原始响应仍在 {raw_dir}，可先 --dump 排查")
    return exit_code


def _dump(manifest_path: Path, responses: list[dict], candidates: list[str], errors: list[str]) -> None:
    """只读展示抓取结果，便于确认页面是否改版。"""
    print(f"清单：{manifest_path}")
    print(f"响应：{len(responses)} 个，候选：{len(candidates)} 个")
    for index, item in enumerate(responses, 1):
        flag = "候选" if item.get("usage_like") else "跳过"
        print(f"  [{index}] {flag} {item.get('status')} {item.get('bytes')}B {item.get('url')}")
        shape = item.get("shape") or {}
        if shape.get("type") == "list":
            print(f"        list x{shape.get('count')} 字段：{', '.join(shape.get('item_keys') or [])}")
        elif shape.get("type") == "object":
            print(f"        object 字段：{', '.join(shape.get('keys') or [])}")
        if item.get("error"):
            print(f"        错误：{item['error']}")
        if item.get("skipped"):
            print(f"        {item['skipped']}")
    for message in errors:
        print(f"  [error] {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trae_capture",
        description="从 Trae 用量页抓取原始响应并导入 TokenBoard（需可选依赖 Playwright）",
    )
    parser.add_argument("--login", action="store_true", help="打开浏览器让用户登录，保存会话后退出")
    parser.add_argument("--url", default=DEFAULT_URL,
                        help=f"用量页地址，默认 {DEFAULT_URL}（可用环境变量 TRAE_USAGE_URL 覆盖）")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE), help="持久化浏览器 profile 目录")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="抓取结果根目录")
    parser.add_argument("--out", help="本次抓取的输出目录（默认 output-root/时间戳）")
    parser.add_argument("--wait", type=int, default=12, help="打开页面后等待响应的秒数，默认 12")
    parser.add_argument("--timeout", type=int, default=60, help="页面打开超时秒数，默认 60")
    parser.add_argument("--match", action="append", help="追加 URL 关键词，可重复")
    parser.add_argument("--headless", action="store_true", help="无头模式（不建议，登录态过期时看不到页面）")
    parser.add_argument("--browser-path", default=os.environ.get("TRAE_BROWSER_PATH", ""),
                        help="复用已有 Chromium/Chrome 可执行文件，避免重复下载浏览器")
    parser.add_argument("--redact", action="store_true", help="落盘前遮盖标题/路径/账号等隐私字段")
    parser.add_argument("--dump", action="store_true", help="只抓取并展示结果，不导入看板")
    parser.add_argument("--records", metavar="PATH", help="传给 import 的 JSON 记录数组点分路径")
    parser.add_argument("--map", dest="maps", action="append", metavar="FIELD=SOURCE",
                        help="传给 import 的字段映射，可重复")
    parser.add_argument("--platform", default="trae", help="记录归属平台，默认 trae")
    parser.add_argument("--format", choices=("html", "json", "table"), default="html",
                        help="看板输出格式，默认 html")
    parser.add_argument("--dashboard", default="dist/tokenboard-trae.html",
                        help="导入后看板输出路径，默认 dist/tokenboard-trae.html")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = Path(os.path.expanduser(args.profile)).resolve()
    if args.login:
        return run_login(profile, args.url, args.browser_path)
    return run_capture(args)


if __name__ == "__main__":
    sys.exit(main())

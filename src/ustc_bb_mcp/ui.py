"""Loopback-only setup UI for the assignment reminder (`ustc-bb-mcp ui`).

The command serves one local page so a first-time user can pick a provider,
paste the app credential and immediately receive a test mail, without putting
the password on a command line or into an MCP client's context.

Safety boundaries:
  * binds 127.0.0.1 only, on a random port unless one is given;
  * every request must carry the token printed at startup, so another local
    process (or a page in the same browser) cannot bind a mailbox for the user;
  * Host and Origin headers are checked against the listening address, which
    also blocks DNS-rebinding and cross-site form posts;
  * request bodies and headers are never logged, and the credential is only
    ever written to the system keyring.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import Settings
from .errors import BBError
from .reminder import (
    PROVIDERS,
    bind_mail,
    load_state,
    mail_config,
    send_mail,
)
from .ui_page import PAGE

MAX_BODY = 8192
PLACEHOLDERS = {
    "ustc": "pb1234567@mail.ustc.edu.cn",
    "qq": "123456789@qq.com",
}


def _provider_payload() -> list[dict]:
    return [
        {
            "key": key,
            "label": preset["label"],
            "host": f"{preset['host']}:{preset['port']}",
            "credential": preset["credential"],
            "hint": preset["hint"],
            "placeholder": PLACEHOLDERS.get(key, ""),
        }
        for key, preset in PROVIDERS.items()
    ]


def status_payload(settings: Settings) -> dict:
    config = mail_config(settings)
    state = load_state(settings)
    return {
        "configured": bool(config["address"] and config["password"]),
        "address": config["address"],
        # Before the first binding, preselect the school mailbox in the UI.
        "provider": config["provider"] if config["address"] else "ustc",
        "label": config["label"],
        "host": config["host"],
        "port": config["port"],
        "tracked": len(state["seen"]),
        "reminded": len(state["notified"]),
        "providers": _provider_payload(),
    }


def test_mail(settings: Settings) -> dict:
    """Send one plain test message to the bound address."""
    config = mail_config(settings)
    if not config["address"] or not config["password"]:
        raise BBError("mail_not_configured", "尚未绑定邮箱，请先保存地址与凭据。")
    body = (
        "这是一封来自 ustc-bb-mcp 的测试邮件。\n\n"
        f"发件与收件：{config['address']}\n"
        f"发信服务：{config['label']}（{config['host']}:{config['port']}，SSL）\n\n"
        "收到本邮件说明邮件通道与专用凭据都可用。之后作业提醒的规则：\n"
        "1. 新布置的作业：下一次检查时汇总成一封邮件；\n"
        "2. 截止前 24 小时仍未提交：再提醒一次；\n"
        "3. 同一截止时间只提醒一次，截止时间变更会重新提醒；\n"
        "4. 已提交或已评分的作业不会打扰你。\n\n"
        "—— ustc-bb-mcp\n"
    )
    send_mail(config, "【USTC BB 测试】作业提醒邮件通道", body)
    return {"sent": True, "to": config["address"], "host": config["host"], "port": config["port"]}


def check_now(settings: Settings) -> dict:
    from .reminder import check_once

    return asyncio.run(check_once(settings))


class Handler(BaseHTTPRequestHandler):
    server_version = "ustc-bb-mcp-ui"
    sys_version = ""
    settings: Settings
    token: str
    port: int

    # Silence the default access log: URLs carry the token.
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def _host_ok(self) -> bool:
        return (self.headers.get("Host") or "") in self._allowed_hosts()

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True  # same-origin navigations and curl-style callers
        return origin in {f"http://{host}" for host in self._allowed_hosts()}

    def _token_ok(self, query: dict) -> bool:
        supplied = self.headers.get("X-Token") or (query.get("t") or [""])[0]
        return bool(supplied) and secrets.compare_digest(supplied, self.token)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, exc: BBError) -> None:
        code = 400 if exc.code in {"invalid_config", "invalid_argument"} else 502
        self._json({"message": exc.message, "code": exc.code}, code)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._host_ok():
            self._json({"message": "非法的 Host 头。"}, 403)
            return
        if not self._token_ok(query):
            self._send(403, "本次启动的链接已失效，请回到终端复制最新打印的地址。"
                            .encode(), "text/plain; charset=utf-8")
            return
        if parsed.path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/status":
            try:
                self._json(status_payload(self.settings))
            except BBError as exc:
                self._error(exc)
            return
        self._json({"message": "未知路径。"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not (self._host_ok() and self._origin_ok() and self._token_ok(parse_qs(parsed.query))):
            self._json({"message": "请求未通过来源校验。"}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._json({"message": "请求体过大。"}, 413)
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json({"message": "请求体格式错误。"}, 400)
            return
        if not isinstance(payload, dict):
            self._json({"message": "请求体格式错误。"}, 400)
            return
        route = {
            "/api/bind": self._bind,
            "/api/test": lambda _: test_mail(self.settings),
            "/api/check": lambda _: check_now(self.settings),
        }.get(parsed.path)
        if route is None:
            self._json({"message": "未知路径。"}, 404)
            return
        try:
            self._json(route(payload))
        except BBError as exc:
            self._error(exc)
        except Exception:  # never leak tracebacks or request data to the page
            self._json({"message": "操作未完成，请查看终端输出。", "code": "internal_error"}, 500)

    def _bind(self, payload: dict) -> dict:
        address = str(payload.get("address", ""))
        password = str(payload.get("password", ""))
        return bind_mail(self.settings, address, password)


def serve(settings: Settings, port: int = 0, open_browser: bool = True) -> dict:
    """Run the setup UI until Ctrl-C; returns a short summary."""
    token = secrets.token_urlsafe(24)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    bound_port = httpd.server_address[1]
    Handler.settings = settings
    Handler.token = token
    Handler.port = bound_port
    url = f"http://127.0.0.1:{bound_port}/?t={token}"
    print(f"邮箱绑定页面：{url}", file=sys.stderr)
    print("仅监听本机回环地址；按 Ctrl-C 结束。", file=sys.stderr)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return {"ui_url": url, "closed": True}


def provider_keys() -> list[str]:
    """Exposed for tests: the provider keys the UI offers."""
    return list(PROVIDERS)

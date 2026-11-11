"""Offline tests for the loopback setup UI: no browser, no SMTP, no network."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

import ustc_bb_mcp.ui as ui
from ustc_bb_mcp import config as config_module

TOKEN = "test-token"


@pytest.fixture
def server(tmp_path, monkeypatch):
    settings = SimpleNamespace(data_dir=tmp_path, config_path=tmp_path / "config.json")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ui.Handler)
    ui.Handler.settings = settings
    ui.Handler.token = TOKEN
    ui.Handler.port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], settings
    finally:
        httpd.shutdown()
        httpd.server_close()


def call(port, path, *, token=None, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data)
    if token:
        request.add_header("X-Token", token)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def test_page_requires_token(server):
    port, _ = server
    status, _ = call(port, "/")
    assert status == 403
    status, html = call(port, f"/?t={TOKEN}")
    assert status == 200 and "邮箱绑定" in html
    # The credential input must never be pre-filled from the server.
    assert 'type="password"' in html


def test_status_requires_token_and_lists_providers(server):
    port, _ = server
    assert call(port, "/api/status")[0] == 403
    status, payload = call(port, "/api/status", token=TOKEN)
    data = json.loads(payload)
    assert status == 200
    assert [item["key"] for item in data["providers"]] == ["ustc", "qq"]
    assert data["configured"] is False and data["address"] == ""
    qq = next(item for item in data["providers"] if item["key"] == "qq")
    assert qq["host"] == "smtp.qq.com:465" and qq["credential"] == "授权码"


def test_bind_saves_to_keyring_and_returns_no_secret(server, monkeypatch):
    port, settings = server
    stored = {}

    class Backend:
        def set_password(self, service, account, password):
            stored[(service, account)] = password

    monkeypatch.setattr(config_module, "_secure_keyring", lambda: Backend())
    status, payload = call(port, "/api/bind", token=TOKEN,
                           body={"address": "123456789@qq.com", "password": "auth-code"})
    assert status == 200
    assert "auth-code" not in payload
    assert json.loads(payload)["provider"] == "qq"
    assert list(stored.values()) == ["auth-code"]
    written = json.loads(settings.config_path.read_text(encoding="utf-8"))
    assert written["mail_address"] == "123456789@qq.com"
    assert "auth-code" not in json.dumps(written)
    # After binding, the status endpoint reports the address but never the secret.
    status_payload = call(port, "/api/status", token=TOKEN)[1]
    assert json.loads(status_payload)["address"] == "123456789@qq.com"


def test_bind_rejects_unknown_domain_with_400(server):
    port, _ = server
    status, payload = call(port, "/api/bind", token=TOKEN,
                           body={"address": "nobody@example.com", "password": "x"})
    assert status == 400
    assert json.loads(payload)["code"] == "invalid_config"


def test_cross_site_and_wrong_host_requests_are_refused(server):
    port, _ = server
    status, _ = call(port, "/api/bind", token=TOKEN, body={}, headers={"Origin": "http://evil.test"})
    assert status == 403
    status, _ = call(port, "/api/status", token=TOKEN, headers={"Host": "evil.test"})
    assert status == 403


def test_test_mail_without_binding_reports_actionable_error(server):
    port, _ = server
    status, payload = call(port, "/api/test", token=TOKEN, body={})
    assert status == 502
    assert json.loads(payload)["code"] == "mail_not_configured"

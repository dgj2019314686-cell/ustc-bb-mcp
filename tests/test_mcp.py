import os
import sys
from pathlib import Path

import httpx
from mcp import Client, StdioServerParameters

from ustc_bb_mcp.auth import Session
from ustc_bb_mcp.config import Settings
from ustc_bb_mcp.errors import BBError
from ustc_bb_mcp.server import create_server

TOOLS = {
    "bb_login", "bb_status", "bb_list_courses", "bb_list_course_files",
    "bb_download_courseware", "bb_list_assignments", "bb_assignment_details",
    "bb_announcements", "bb_submit_assignment",
    "bb_reminder_status", "bb_check_reminders",
}


async def test_handshake_schema_calls_and_structured_error(tmp_path):
    def handler(request):
        if "portal" in request.url.path:
            return httpx.Response(200, text='<a href="/?action=logout">Logout</a><a href="/webapps/blackboard/execute/launcher?type=Course&id=_1_1">CS.2026FA: Test course</a>')
        return httpx.Response(200, text='<div id="courseMenuPalette_contents"></div>')
    settings = Settings(data_dir=tmp_path / "state", output_dir=tmp_path / "out")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    session = Session(settings, client=http)
    async with Client(create_server(settings, session=session)) as client:
        listing = await client.list_tools()
        tools = {tool.name: tool for tool in listing.tools}
        assert set(tools) == TOOLS
        assert tools["bb_submit_assignment"].input_schema["properties"]["confirm"]["default"] is False
        assert "preview_token" in tools["bb_submit_assignment"].input_schema["properties"]
        assert tools["bb_list_courses"].output_schema is not None
        for name in ("bb_login", "bb_status", "bb_list_courses"):
            result = await client.call_tool(name)
            assert result.structured_content["ok"] is True
            assert result.structured_content["checked_at"]
        reminder = await client.call_tool("bb_reminder_status")
        assert reminder.structured_content["ok"] is True
        assert reminder.structured_content["data"]["mail_configured"] is False
        assert "setup_command" in reminder.structured_content["data"]
        assert "password" not in str(reminder.structured_content["data"])
        result = await client.call_tool("bb_list_course_files", {"course": "missing"})
        assert result.structured_content["ok"] is False
        assert result.structured_content["error"]["code"] == "not_found"
        assert "secret" not in str(result.structured_content)
    await http.aclose()


async def test_unexpected_error_never_echoes_authenticated_url(tmp_path):
    class FailedSession:
        async def ensure_session(self, **kwargs):
            raise RuntimeError("password=secret&ticket=private")

        async def close(self):
            pass

    settings = Settings(data_dir=tmp_path)
    async with Client(create_server(settings, session=FailedSession())) as client:
        result = await client.call_tool("bb_status")
        assert result.structured_content["error"]["code"] == "operation_failed"
        assert "secret" not in str(result)
        assert "private" not in str(result)


async def test_stdio_subprocess_startup_and_no_stdout_noise(tmp_path):
    environment = {**os.environ, "BB_DATA_DIR": str(tmp_path / "clean-state")}
    # A real subprocess handshake detects accidental stdout diagnostics before JSON-RPC.
    server = StdioServerParameters(command=sys.executable, args=["-m", "ustc_bb_mcp.cli", "serve"], env=environment)
    async with Client(server) as client:
        result = await client.list_tools()
        assert {tool.name for tool in result.tools} == TOOLS
        invalid = await client.call_tool("bb_submit_assignment", {
            "course": "_1_1", "assignment": "_2_1", "file_path": str(tmp_path / "missing"), "confirm": True,
        })
        assert invalid.structured_content["error"]["code"] == "preview_required"


def test_cli_doctor_is_offline(tmp_path, monkeypatch):
    from ustc_bb_mcp.cli import doctor
    def forbidden(*args, **kwargs):
        raise BBError("network_used", "doctor must not access the network")
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    report = doctor(Settings(data_dir=tmp_path / "state", output_dir=tmp_path / "out"))
    assert report["network_checked"] is False
    assert report["mcp"] == "2.3.0"
    assert not (tmp_path / "state").exists()
    assert "password" not in report and "cookies" not in report


def test_cli_commands_and_safe_error(tmp_path):
    import subprocess
    environment = {**os.environ, "BB_DATA_DIR": str(tmp_path), "BB_BASE_URL": "https://invalid.example"}
    result = subprocess.run([sys.executable, "-m", "ustc_bb_mcp.cli", "doctor"], capture_output=True, text=True, encoding="utf-8", env=environment)
    assert result.returncode == 1
    assert "invalid_config" in result.stderr
    assert not result.stdout
    root = Path(__file__).resolve().parents[1]
    assert (root / "uv.lock").is_file()

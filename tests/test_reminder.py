"""Offline tests for the e-mail reminder: no SMTP server and no Blackboard access."""

import json
import smtplib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import ustc_bb_mcp.reminder as reminder
from ustc_bb_mcp.errors import BBError
from ustc_bb_mcp.models import Result
from ustc_bb_mcp.reminder import (
    check_once,
    digest_mail,
    ensure_mail_configured,
    evaluate,
    load_state,
    mail_config,
    save_state,
    send_mail,
)


def settings(tmp_path):
    return SimpleNamespace(data_dir=tmp_path, config_path=tmp_path / "config.json")


NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
SOON = (NOW + timedelta(hours=10)).isoformat()
LATER = (NOW + timedelta(days=5)).isoformat()


def item(assignment_id="_101_1", course_id="_101_1", status="not_submitted", due_at=SOON, **extra):
    return {"id": assignment_id, "course_id": course_id, "name": "作业一",
            "url": "https://www.bb.ustc.edu.cn/a", "kind": "assignment", "due_at": due_at,
            "due_text": None, "status": status, "grade": None,
            "course_name": "数据结构", **extra}


def empty_state():
    return {"seen": {}, "notified": {}}


def test_evaluate_bootstrap_records_baseline_without_notifications():
    outcome = evaluate([item(assignment_id="a"),
                        item(assignment_id="b", due_at=LATER, status="submitted")],
                       empty_state(), NOW, bootstrap=True)
    assert outcome["new"] == []
    assert outcome["due_soon"] == []
    assert len(outcome["state"]["seen"]) == 2


def test_evaluate_flags_new_assignments_and_ignores_finished_ones():
    state = {"seen": {"_101_1:a": {"first_seen": "", "status": ""}}, "notified": {}}
    outcome = evaluate([item(assignment_id="a"),
                        item(assignment_id="b", status="submitted"),
                        item(assignment_id="c")], state, NOW)
    assert [entry["id"] for entry in outcome["new"]] == ["c"]
    assert outcome["state"]["seen"]["_101_1:b"]["status"] == "submitted"


def test_evaluate_only_reminds_within_24_hours_and_not_repeated():
    outcome = evaluate([item(assignment_id="near"), item(assignment_id="far", due_at=LATER)],
                       empty_state(), NOW)
    assert [entry["id"] for entry in outcome["due_soon"]] == ["near"]
    key = "_101_1:near"
    assert outcome["state"]["notified"][key] == SOON
    # Same due date is not reminded twice.
    second = evaluate([item(assignment_id="near")], outcome["state"], NOW + timedelta(minutes=5))
    assert second["due_soon"] == []
    # A changed due date re-arms the reminder.
    new_due = (NOW + timedelta(hours=12)).isoformat()
    third = evaluate([item(assignment_id="near", due_at=new_due)], outcome["state"],
                     NOW + timedelta(minutes=5))
    assert [entry["id"] for entry in third["due_soon"]] == ["near"]


def test_evaluate_skips_submitted_and_past_due():
    past = (NOW - timedelta(hours=1)).isoformat()
    outcome = evaluate([item(assignment_id="done", status="submitted"),
                        item(assignment_id="late", due_at=past),
                        item(assignment_id="nodue", due_at=None)], empty_state(), NOW)
    assert outcome["due_soon"] == []
    # Only the no-due-date item is reported as new; finished and past-due ones
    # are recorded silently.
    assert [entry["id"] for entry in outcome["new"]] == ["nodue"]


def test_digest_mail_lists_course_name_and_due_date():
    subject, body = digest_mail([item()], [item(assignment_id="b", status="draft")])
    assert "1 个新作业" in subject and "1 个作业将在 24 小时内截止" in subject
    assert "数据结构：作业一" in body and "数据结构：作业一" in body
    assert "状态：草稿" in body


def test_state_roundtrip(tmp_path):
    config = settings(tmp_path)
    state = {"seen": {"k": {"first_seen": NOW.isoformat(), "status": ""}}, "notified": {"k": SOON}}
    save_state(config, state)
    assert load_state(config) == state
    assert (tmp_path / "reminder-state.json").is_file()


def test_mail_config_prefers_environment(monkeypatch, tmp_path):
    config = settings(tmp_path)
    monkeypatch.setenv("BB_MAIL_USR", "pb1234567@mail.ustc.edu.cn")
    monkeypatch.setenv("BB_MAIL_PWD", "secret")
    mail = mail_config(config)
    assert mail["address"] == "pb1234567@mail.ustc.edu.cn"
    assert mail["password"] == "secret"
    assert mail["host"] == "mail.ustc.edu.cn" and mail["port"] == 465


class FakeTTY:
    def isatty(self):
        return True


def test_ensure_mail_configured_runs_wizard_only_on_tty(monkeypatch, tmp_path):
    config = settings(tmp_path)
    monkeypatch.delenv("BB_MAIL_USR", raising=False)
    monkeypatch.delenv("BB_MAIL_PWD", raising=False)
    calls = []

    def fake_configure(target):
        calls.append(target)
        target.config_path.write_text(
            json.dumps({"mail_address": "pb1234567@mail.ustc.edu.cn"}), encoding="utf-8")
        monkeypatch.setenv("BB_MAIL_PWD", "pw")
        return {}

    monkeypatch.setattr(reminder, "configure_mail", fake_configure)
    # Non-interactive (cron, MCP): fail with guidance instead of hanging.
    with pytest.raises(BBError) as error:
        ensure_mail_configured(config)
    assert error.value.code == "mail_not_configured"
    assert calls == []
    # Interactive first run: the wizard runs once and the settings are reused.
    monkeypatch.setattr(reminder.sys, "stdin", FakeTTY())
    mail = ensure_mail_configured(config)
    assert calls == [config]
    assert mail["address"] == "pb1234567@mail.ustc.edu.cn" and mail["password"] == "pw"


class FakeSMTP:
    calls = []

    def __init__(self, host, port, timeout=30):
        FakeSMTP.calls.append({"host": host, "port": port})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, user, password):
        FakeSMTP.calls[-1]["user"] = user

    def send_message(self, message):
        FakeSMTP.calls[-1]["subject"] = message["Subject"]
        FakeSMTP.calls[-1]["to"] = message["To"]


def test_send_mail_uses_ssl_and_school_smtp(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.calls = []
    send_mail({"address": "pb1234567@mail.ustc.edu.cn", "password": "pw",
               "host": "smtp.ustc.edu.cn", "port": 465}, "主题", "正文")
    call = FakeSMTP.calls[0]
    assert call["host"] == "smtp.ustc.edu.cn" and call["port"] == 465
    assert call["user"] == "pb1234567@mail.ustc.edu.cn"
    assert call["subject"] == "主题" and call["to"] == "pb1234567@mail.ustc.edu.cn"


def test_send_mail_wraps_smtp_errors(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("connection refused")
    monkeypatch.setattr(smtplib, "SMTP_SSL", broken)
    with pytest.raises(BBError) as error:
        send_mail({"address": "a@mail.ustc.edu.cn", "password": "pw",
                   "host": "smtp.ustc.edu.cn", "port": 465}, "主题", "正文")
    assert error.value.code == "mail_send_failed"


class FakeBB:
    def __init__(self, items):
        self.items = items
        self.calls = []

    async def list_assignments(self, query):
        self.calls.append(query)
        return Result(message="ok", data={"assignments": self.items})


async def test_check_once_sends_digest_and_persists_state(tmp_path, monkeypatch):
    config = settings(tmp_path)
    monkeypatch.setenv("BB_MAIL_USR", "pb1234567@mail.ustc.edu.cn")
    monkeypatch.setenv("BB_MAIL_PWD", "secret")
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.calls = []
    # First run is a baseline: records state, sends nothing.
    first = await check_once(config, bb=FakeBB([item(assignment_id="a")]))
    assert first["mail_sent"] is False and first["assignments_checked"] == 1
    # A new assignment appears and is due soon: one digest mail is sent.
    second = await check_once(config, bb=FakeBB([
        item(assignment_id="a"), item(assignment_id="b", status="draft")]))
    # "b" is new, and both items are due within 24 hours: the baseline no longer
    # consumes "a"'s upcoming deadline, so both are reminded.
    assert second["new_assignments"] == 1 and second["due_soon"] == 2
    assert second["mail_sent"] is True
    assert "作业提醒" in FakeSMTP.calls[0]["subject"]
    stored = json.loads((tmp_path / "reminder-state.json").read_text(encoding="utf-8"))
    assert "_101_1:b" in stored["seen"]


async def test_check_once_without_mail_config_raises(tmp_path, monkeypatch):
    config = settings(tmp_path)
    monkeypatch.delenv("BB_MAIL_USR", raising=False)
    monkeypatch.delenv("BB_MAIL_PWD", raising=False)
    (tmp_path / "reminder-state.json").write_text(
        json.dumps({"seen": {}, "notified": {}}), encoding="utf-8")
    with pytest.raises(BBError) as error:
        await check_once(config, bb=FakeBB([item()]))
    assert error.value.code == "mail_not_configured"


def test_detect_provider_maps_known_domains():
    assert reminder.detect_provider("pb1234567@mail.ustc.edu.cn") == "ustc"
    assert reminder.detect_provider("student@ustc.edu.cn") == "ustc"
    assert reminder.detect_provider("123456789@qq.com") == "qq"
    assert reminder.detect_provider("someone@foxmail.com") == "qq"
    assert reminder.detect_provider("nobody@example.com") == "custom"
    assert reminder.detect_provider("not-an-address") == "custom"


def test_mail_config_uses_qq_smtp_for_qq_address(monkeypatch, tmp_path):
    monkeypatch.setenv("BB_MAIL_USR", "123456789@qq.com")
    monkeypatch.setenv("BB_MAIL_PWD", "auth-code")
    mail = mail_config(settings(tmp_path))
    assert mail["provider"] == "qq" and mail["label"] == "QQ 邮箱"
    assert mail["host"] == "smtp.qq.com" and mail["port"] == 465
    assert mail["credential"] == "授权码"


def test_mail_config_explicit_host_beats_provider_default(monkeypatch, tmp_path):
    monkeypatch.setenv("BB_MAIL_USR", "123456789@qq.com")
    monkeypatch.setenv("BB_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("BB_SMTP_PORT", "2525")
    mail = mail_config(settings(tmp_path))
    assert mail["host"] == "127.0.0.1" and mail["port"] == 2525


class Backend:
    def __init__(self):
        self.stored = {}

    def set_password(self, service, account, password):
        self.stored[(service, account)] = password


def test_bind_mail_stores_credential_in_keyring_only(monkeypatch, tmp_path):
    from ustc_bb_mcp import config as config_module

    backend = Backend()
    monkeypatch.setattr(config_module, "_secure_keyring", lambda: backend)
    result = reminder.bind_mail(settings(tmp_path), " 123456789@qq.com ", "auth-code")
    assert result["configured"] is True and result["provider"] == "qq"
    assert result["smtp_host"] == "smtp.qq.com"
    assert "password" not in result and "auth-code" not in json.dumps(result)
    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert stored["mail_address"] == "123456789@qq.com" and stored["mail_provider"] == "qq"
    assert "auth-code" not in json.dumps(stored)


def test_bind_mail_rejects_unknown_provider_and_empty_credential(monkeypatch, tmp_path):
    from ustc_bb_mcp import config as config_module

    monkeypatch.setattr(config_module, "_secure_keyring", lambda: Backend())
    with pytest.raises(BBError) as error:
        reminder.bind_mail(settings(tmp_path), "nobody@example.com", "x")
    assert error.value.code == "invalid_config"
    with pytest.raises(BBError) as error:
        reminder.bind_mail(settings(tmp_path), "123456789@qq.com", "  ")
    assert error.value.code == "invalid_config"


async def test_check_once_dry_run_reports_without_sending_or_advancing(tmp_path, monkeypatch):
    config = settings(tmp_path)
    # A baseline already exists (the user has run a check before).
    (tmp_path / "reminder-state.json").write_text(
        json.dumps({"seen": {}, "notified": {}}), encoding="utf-8")
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.calls = []
    preview = await check_once(config, bb=FakeBB([item(assignment_id="a")]), dry_run=True)
    assert preview["dry_run"] is True and preview["mail_sent"] is False
    assert preview["new_assignments"] == 1
    # A preview must not consume the notification or write state.
    assert FakeSMTP.calls == []
    stored = json.loads((tmp_path / "reminder-state.json").read_text(encoding="utf-8"))
    assert stored["seen"] == {} and "last_check" not in stored


async def test_check_once_records_last_check_time(tmp_path, monkeypatch):
    config = settings(tmp_path)
    monkeypatch.setenv("BB_MAIL_PWD", "pw")
    monkeypatch.setenv("BB_MAIL_USR", "pb1234567@mail.ustc.edu.cn")
    await check_once(config, bb=FakeBB([item(assignment_id="a")]))
    stored = json.loads((tmp_path / "reminder-state.json").read_text(encoding="utf-8"))
    assert stored["last_check"] and "_101_1:a" in stored["seen"]


def test_mask_address_hides_local_part():
    assert reminder.mask_address("dgj738506330@mail.ustc.edu.cn") == "dgj*********@mail.ustc.edu.cn"
    assert reminder.mask_address("ab@qq.com") == "ab*@qq.com"
    assert reminder.mask_address("") == ""


class FakeDueBB(FakeBB):
    """Reports assignments whose deadlines only exist on the detail page."""

    def __init__(self, items, due):
        super().__init__(items)
        self.due = due
        self.due_calls = []

    async def due_dates(self, items):
        self.due_calls.append([f"{i['course_id']}:{i['id']}" for i in items])
        return {f"{i['course_id']}:{i['id']}": v for i, v in
                ((i, self.due.get(f"{i['course_id']}:{i['id']}")) for i in items) if v}, []


async def test_check_once_reads_deadlines_from_detail_pages_and_caches(tmp_path, monkeypatch):
    config = settings(tmp_path)
    monkeypatch.setenv("BB_MAIL_USR", "pb1234567@mail.ustc.edu.cn")
    monkeypatch.setenv("BB_MAIL_PWD", "pw")
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    FakeSMTP.calls = []
    soon = (datetime.now(UTC) + timedelta(hours=6)).isoformat()
    bb = FakeDueBB([item(assignment_id="x", due_at=None)],
                   {"_101_1:x": {"due_at": soon, "due_text": "明天 12:00"}})
    # Baseline run records state; the deadline is resolved during this pass.
    first = await check_once(config, bb=bb)
    assert first["assignments_checked"] == 1
    assert len(bb.due_calls) == 1
    stored = json.loads((tmp_path / "reminder-state.json").read_text(encoding="utf-8"))
    assert stored["due_cache"]["_101_1:x"]["due_at"] == soon
    # Deadline is cached, so the next check does not open the page again.
    second = await check_once(config, bb=bb)
    assert len(bb.due_calls) == 1
    assert second["due_soon"] == 1 and second["mail_sent"] is True
    assert "作业提醒" in FakeSMTP.calls[0]["subject"]


async def test_check_once_skips_detail_pages_for_submitted_and_tests(tmp_path):
    config = settings(tmp_path)
    bb = FakeDueBB([item(assignment_id="done", status="submitted", due_at=None),
                    item(assignment_id="quiz", kind="test", due_at=None)], {})
    await check_once(config, bb=bb, dry_run=True)
    assert bb.due_calls in ([], [[]])
    assert not (tmp_path / "reminder-state.json").exists()


def test_parse_due_reads_labelled_detail_row():
    from ustc_bb_mcp.parsing import parse_due

    html = ('<div id="content"><table><tr><td class="metaLabel">截止日期</td>'
            '<td class="metaField">2026年12月7日 星期一 下午5:00</td></tr></table></div>')
    due, text = parse_due(html)
    assert due and due.startswith("2026-12-07T17:00") and "2026年12月7日" in text
    assert parse_due("<div>没有日期</div>") == (None, None)


def test_bootstrap_does_not_consume_upcoming_deadline():
    outcome = evaluate([item(assignment_id="near")], empty_state(), NOW, bootstrap=True)
    assert outcome["new"] == [] and outcome["due_soon"] == []
    # The baseline must not mark the deadline as already reminded.
    assert outcome["state"]["notified"] == {}
    later = evaluate([item(assignment_id="near")], outcome["state"], NOW + timedelta(minutes=30))
    assert [entry["id"] for entry in later["due_soon"]] == ["near"]

"""Optional scheduled e-mail reminders for new assignments and approaching deadlines.

The reminder is deliberately a fixed periodic check, not an agent: it lists
assignments, recognises only the course name and the due date, and sends a
digest e-mail through the user's USTC mailbox (mail.ustc.edu.cn:465, SSL).
USTC mail does not accept the CAS login password for SMTP; the official
client setup requires a 16-character client-specific password, which can be
generated and revoked at mail.ustc.edu.cn under 设置 → 安全设置 → 客户端专用密码.
It never decides anything on the user's behalf and never submits coursework.
"""

from __future__ import annotations

import asyncio
import json
import os
import smtplib
import sys
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate

import keyring

from .config import KEYRING_SERVICE, Settings, private_json
from .errors import BBError

SMTP_HOST = "mail.ustc.edu.cn"
SMTP_PORT = 465
STATE_FILE = "reminder-state.json"
DUE_WINDOW = timedelta(hours=24)
STATUS_LABELS = {"not_submitted": "未提交", "draft": "草稿", "unknown": "未知"}


def _read_config(settings: Settings) -> dict:
    try:
        config = json.loads(settings.config_path.read_text(encoding="utf-8"))
        return config if isinstance(config, dict) else {}
    except (OSError, ValueError):
        return {}


def mail_config(settings: Settings) -> dict:
    config = _read_config(settings)
    address = os.environ.get("BB_MAIL_USR", config.get("mail_address", "")).strip()
    host = os.environ.get("BB_SMTP_HOST", config.get("smtp_host", SMTP_HOST))
    try:
        port = int(os.environ.get("BB_SMTP_PORT", config.get("smtp_port", SMTP_PORT)))
    except ValueError as exc:
        raise BBError("invalid_config", "SMTP 端口必须是整数。") from exc
    password = os.environ.get("BB_MAIL_PWD", "")
    if not password and address:
        try:
            password = keyring.get_password(KEYRING_SERVICE, f"mail:{address}") or ""
        except Exception:
            password = ""
    return {"address": address, "password": password, "host": host, "port": port}


def configure_mail(settings: Settings) -> dict:
    from getpass import getpass

    from .config import _secure_keyring

    address = input("科大邮箱地址（例如 pb1234567@mail.ustc.edu.cn）: ").strip()
    if not address.endswith("@ustc.edu.cn"):
        raise BBError("invalid_config", "请使用科大邮箱地址（@ustc.edu.cn 或 @mail.ustc.edu.cn）。")
    password = getpass.getpass(
        "客户端专用密码（16 位；mail.ustc.edu.cn → 设置 → 安全设置 → 客户端专用密码 生成，"
        "统一身份认证密码不能用于 SMTP）: "
    )
    if not password:
        raise BBError("invalid_config", "密码不能为空。")
    try:
        _secure_keyring().set_password(KEYRING_SERVICE, f"mail:{address}", password)
    except Exception as exc:
        raise BBError("credential_store_unavailable", "无法写入系统凭据库；未保存明文密码。") from exc
    config = _read_config(settings)
    config["mail_address"] = address
    private_json(settings.config_path, config)
    return {"configured": True, "mail_address": address, "smtp_host": SMTP_HOST,
            "password_storage": "system_keyring"}


def ensure_mail_configured(settings: Settings) -> dict:
    """Return usable mail settings; on first interactive use, run the wizard.

    Blackboard and the mailbox are separate systems, so a first-time user has
    no mail settings yet. In an interactive terminal the reminder binds the
    mailbox once instead of failing; non-interactive callers (cron, MCP) still
    get a clear error instead of a hung prompt.
    """
    config = mail_config(settings)
    if config["address"] and config["password"]:
        return config
    if not sys.stdin.isatty():
        raise BBError(
            "mail_not_configured",
            "尚未绑定邮箱。请运行 ustc-bb-mcp mail-configure，或设置 BB_MAIL_USR/BB_MAIL_PWD。",
        )
    print("首次使用需要绑定科大邮箱（Blackboard 与邮箱是两套系统，只需绑定一次）。", file=sys.stderr)
    print("请填写 mail.ustc.edu.cn 生成的客户端专用密码，统一身份认证密码无法用于 SMTP。", file=sys.stderr)
    configure_mail(settings)
    config = mail_config(settings)
    if not config["address"] or not config["password"]:
        raise BBError("mail_not_configured", "邮箱绑定未完成，请重新运行 ustc-bb-mcp mail-configure。")
    return config


def send_mail(config: dict, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = config["address"]
    message["To"] = config["address"]
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message.set_content(body)
    try:
        with smtplib.SMTP_SSL(config["host"], config["port"], timeout=30) as server:
            server.login(config["address"], config["password"])
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise BBError("mail_send_failed",
                      "邮件发送失败，请检查 SMTP 地址、端口、密码与校园网连接。") from exc


def load_state(settings: Settings) -> dict:
    path = settings.data_dir / STATE_FILE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(state, dict) and isinstance(state.get("seen"), dict) and isinstance(state.get("notified"), dict):
            return state
    except (OSError, ValueError):
        pass
    return {"seen": {}, "notified": {}}


def save_state(settings: Settings, state: dict) -> None:
    private_json(settings.data_dir / STATE_FILE, state)


def _due_datetime(due_at: str | None) -> datetime | None:
    if not due_at:
        return None
    try:
        due = datetime.fromisoformat(due_at)
    except ValueError:
        return None
    return due if due.tzinfo else due.replace(tzinfo=UTC)


def evaluate(items: list[dict], state: dict, now: datetime, *, bootstrap: bool = False) -> dict:
    """Classify assignment items against stored state; returns the digest parts
    and the updated state. Pure function over the given inputs."""
    seen, notified = state["seen"], state["notified"]
    new_items, due_soon = [], []
    for item in items:
        key = f"{item.get('course_id', '')}:{item.get('id', '')}"
        status = item.get("status", "unknown")
        if status in {"submitted", "graded"}:
            seen.setdefault(key, {"first_seen": now.isoformat(), "status": status})
            continue
        if key not in seen:
            seen[key] = {"first_seen": now.isoformat(), "status": status}
            # An assignment that is already past due when first discovered is
            # not worth a "new homework" e-mail.
            due_preview = _due_datetime(item.get("due_at"))
            if not bootstrap and (due_preview is None or due_preview > now):
                new_items.append(item)
        due = _due_datetime(item.get("due_at"))
        if due is None or not now < due <= now + DUE_WINDOW:
            continue
        if notified.get(key) == item["due_at"]:
            continue
        notified[key] = item["due_at"]
        if not bootstrap:
            due_soon.append(item)
    return {"new": new_items, "due_soon": due_soon,
            "state": {"seen": seen, "notified": notified}}


def digest_mail(new_items: list[dict], due_soon: list[dict]) -> tuple[str, str]:
    """Build one plain-text digest e-mail; returns (subject, body)."""
    parts = []
    if new_items:
        parts.append(f"{len(new_items)} 个新作业")
    if due_soon:
        parts.append(f"{len(due_soon)} 个作业将在 24 小时内截止")
    subject = "【USTC BB 作业提醒】" + ("、".join(parts) if parts else "暂无需要处理的事项")
    lines = []
    if new_items:
        lines.append("== 新布置的作业 ==")
        for item in new_items:
            due = item.get("due_text") or item.get("due_at") or "未知"
            lines.append(f"- {item.get('course_name', '未知课程')}：{item.get('name', '')}（截止：{due}）")
            lines.append(f"  链接：{item.get('url', '')}")
    if due_soon:
        if lines:
            lines.append("")
        lines.append("== 24 小时内截止 ==")
        for item in due_soon:
            due = item.get("due_text") or item.get("due_at") or "未知"
            label = STATUS_LABELS.get(item.get("status", "unknown"), "未知")
            lines.append(f"- {item.get('course_name', '未知课程')}：{item.get('name', '')}（截止：{due}，状态：{label}）")
            lines.append(f"  链接：{item.get('url', '')}")
    body = "\n".join(lines) + "\n\n来自本机 ustc-bb-mcp remind；提交作业请通过 Blackboard 页面或 bb_submit_assignment 确认后完成。\n"
    return subject, body


async def check_once(settings: Settings, bb=None, *, send: bool = True) -> dict:
    """Run one check: list assignments, compare with state, mail the digest."""
    if bb is None:
        from .auth import Session
        from .service import Blackboard

        session = Session(settings)
        try:
            bb = Blackboard(session, settings)
            result = await bb.list_assignments("all")
        finally:
            await session.close()
    else:
        result = await bb.list_assignments("all")
    items = result.data.get("assignments", [])
    now = datetime.now(UTC)
    state_path = settings.data_dir / STATE_FILE
    state = load_state(settings)
    outcome = evaluate(items, state, now, bootstrap=not state_path.exists())
    new_items, due_soon = outcome["new"], outcome["due_soon"]
    sent = False
    if new_items or due_soon:
        if send:
            config = ensure_mail_configured(settings)
            subject, body = digest_mail(new_items, due_soon)
            send_mail(config, subject, body)
        # Persist only after a successful send so a failure is retried next run.
        save_state(settings, outcome["state"])
        sent = send
    else:
        save_state(settings, outcome["state"])
    return {"checked_at": now.isoformat(), "assignments_checked": len(items),
            "new_assignments": len(new_items), "due_soon": len(due_soon),
            "mail_sent": sent, "complete": result.complete, "warnings": result.warnings}


async def run_reminder(settings: Settings, interval_minutes: float) -> None:
    if interval_minutes <= 0:
        raise BBError("invalid_argument", "检查间隔必须大于零分钟。")
    while True:
        try:
            result = await check_once(settings)
            print(f"remind: 新作业 {result['new_assignments']} 个，"
                  f"24 小时内截止 {result['due_soon']} 个，"
                  f"已发邮件 {result['mail_sent']}", file=sys.stderr)
        except BBError as error:
            print(f"remind: 本次检查未完成（{error.code}），将在下个周期重试。", file=sys.stderr)
        await asyncio.sleep(interval_minutes * 60)

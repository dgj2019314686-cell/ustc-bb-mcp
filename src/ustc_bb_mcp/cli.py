"""Local setup commands. Only `serve` uses stdout for the MCP protocol."""

import argparse
import asyncio
import importlib.metadata
import json
import logging
import sys
from pathlib import Path

from .auth import Session
from .config import Settings, configure
from .errors import BBError


def doctor(settings: Settings) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        chromium = Path(playwright.chromium.executable_path)
    return {"python": sys.version.split()[0], "mcp": importlib.metadata.version("mcp"),
            "pyustc": importlib.metadata.version("pyustc"),
            "chromium_installed": chromium.is_file(), "data_dir": str(settings.data_dir),
            "output_dir": str(settings.output_dir), "session_file_present": settings.state_path.is_file(),
            "account_configured": bool(settings.username), "network_checked": False}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="ustc-bb-mcp", description="中科大 Blackboard 本地 MCP 服务")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="启动 stdio MCP 服务")
    config_parser = commands.add_parser("configure", help="将密码存入系统凭据库")
    config_parser.add_argument("--username")
    commands.add_parser("mail-configure", help="在终端里绑定发信邮箱（科大邮箱或 QQ 邮箱）")
    ui_parser = commands.add_parser("ui", help="启动本机邮箱绑定页面（仅监听 127.0.0.1）")
    ui_parser.add_argument("--port", type=int, default=0, help="监听端口，默认随机可用端口")
    ui_parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    remind_parser = commands.add_parser("remind", help="定时检查作业并通过科大邮箱提醒（无 agent）")
    remind_parser.add_argument("--interval", type=float, default=60, help="检查间隔（分钟），默认 60")
    remind_parser.add_argument("--once", action="store_true", help="只检查一次，适合系统定时任务")
    login_parser = commands.add_parser("login", help="登录 BB 并保存会话")
    login_parser.add_argument("--browser", action="store_true", help="在独立浏览器中人工认证")
    login_parser.add_argument("--channel", choices=["msedge", "chrome"],
                              help="使用已安装的 Edge/Chrome 登录，免下载 Chromium")
    commands.add_parser("doctor", help="不联网检查安装和配置")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s %(message)s")
    # Never expose HTTP URLs, CAS tickets or request headers through dependency logs.
    for name in ("httpx", "httpcore", "pyustc"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        settings = Settings.load()
        if args.command == "serve":
            from .server import create_server
            create_server(settings).run(transport="stdio")
            return 0
        if args.command == "doctor":
            result = doctor(settings)
        elif args.command == "configure":
            result = configure(settings, args.username)
        elif args.command == "mail-configure":
            from .reminder import configure_mail
            result = configure_mail(settings)
        elif args.command == "ui":
            from .ui import serve
            result = serve(settings, port=args.port, open_browser=not args.no_open)
        elif args.command == "remind":
            from .reminder import check_once, run_reminder

            async def remind():
                if args.once:
                    return await check_once(settings)
                await run_reminder(settings, args.interval)
                return None
            result = asyncio.run(remind())
        else:
            async def login():
                session = Session(settings)
                try:
                    if args.browser:
                        return await session.login_browser(args.channel)
                    return await session.ensure_session()
                finally:
                    await session.close()
            result = asyncio.run(login())
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except BBError as error:
        print(json.dumps(error.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("操作已取消。", file=sys.stderr)
        return 130
    except Exception:
        print("操作未完成，请检查安装、配置和文件权限；未输出敏感诊断信息。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

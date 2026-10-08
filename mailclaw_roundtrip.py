#!/usr/bin/env python3
"""Send a MailClaw email to a fresh catch-all alias and wait for its arrival.

Required environment variables:
  MAILCLAW_HOST       e.g. https://mailclaw.example.workers.dev
  MAILCLAW_API_TOKEN  MailClaw's API_TOKEN Worker secret
  MAILCLAW_FROM       a verified sender, e.g. sender@example.com

Optional environment variables:
  MAILCLAW_DOMAIN             defaults to example.com
  MAILCLAW_POLL_INTERVAL      defaults to 5 seconds
  MAILCLAW_TIMEOUT            defaults to 90 seconds
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


DEFAULT_DOMAIN = "example.com"
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


class MailClawError(RuntimeError):
    """An HTTP or API-level MailClaw error."""


@dataclass(frozen=True)
class Config:
    host: str
    api_token: str
    sender: str
    domain: str
    poll_interval: float
    timeout: float


def load_dotenv(path: str = ENV_FILE) -> None:
    """Load unset environment variables from a local .env file."""
    if not os.path.exists(path):
        return

    with open(path, encoding="utf-8") as env_file:
        for line_number, line in enumerate(env_file, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line.removeprefix("export ").lstrip()
            name, separator, value = line.partition("=")
            name = name.strip()
            if not separator or not name or not name.isidentifier():
                raise MailClawError(f"{path} 第 {line_number} 行格式无效。")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(name, value)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MailClawError(f"缺少环境变量 {name}。")
    return value


def load_config(args: argparse.Namespace) -> Config:
    poll_interval = args.poll_interval or float(os.environ.get("MAILCLAW_POLL_INTERVAL", "5"))
    timeout = args.timeout or float(os.environ.get("MAILCLAW_TIMEOUT", "90"))
    if poll_interval <= 0 or timeout <= 0:
        raise MailClawError("轮询间隔和超时时间必须大于 0。")

    return Config(
        host=required_env("MAILCLAW_HOST").rstrip("/"),
        api_token=required_env("MAILCLAW_API_TOKEN"),
        sender=required_env("MAILCLAW_FROM"),
        domain=os.environ.get("MAILCLAW_DOMAIN", DEFAULT_DOMAIN).strip() or DEFAULT_DOMAIN,
        poll_interval=poll_interval,
        timeout=timeout,
    )


def request_json(
    config: Config,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{config.host}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {config.api_token}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise MailClawError(f"{method} {path} 返回 HTTP {error.code}: {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise MailClawError(f"无法连接 MailClaw：{error.reason}") from error

    try:
        result = json.loads(body)
    except json.JSONDecodeError as error:
        raise MailClawError(f"{method} {path} 未返回 JSON：{body[:500]}") from error

    if result.get("success") is False:
        raise MailClawError(f"{method} {path} 失败：{result}")
    return result


def new_test_address(domain: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"mailclaw-test-{stamp}-{secrets.token_hex(3)}@{domain}"


def send_test_email(config: Config, recipient: str, marker: str) -> dict[str, Any]:
    subject = f"MailClaw round-trip test {marker}"
    return request_json(
        config,
        "POST",
        "/api/emails/send",
        {
            "from": config.sender,
            "to": recipient,
            "subject": subject,
            "text": (
                "This message verifies MailClaw sending, Cloudflare Email Routing, "
                f"and catch-all receiving. Test marker: {marker}"
            ),
        },
    )


def find_received_email(config: Config, recipient: str, marker: str) -> dict[str, Any] | None:
    query = urllib.parse.urlencode({"to": recipient, "limit": 20})
    response = request_json(config, "GET", f"/api/emails?{query}")
    emails = response.get("data", {}).get("emails", [])
    return next((email for email in emails if marker in email.get("subject", "")), None)


def wait_for_email(config: Config, recipient: str, marker: str) -> dict[str, Any] | None:
    deadline = time.monotonic() + config.timeout
    while time.monotonic() < deadline:
        email = find_received_email(config, recipient, marker)
        if email:
            return email
        remaining = max(0, deadline - time.monotonic())
        print(f"尚未收到，{min(config.poll_interval, remaining):.0f} 秒后重试…")
        time.sleep(min(config.poll_interval, remaining))
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MailClaw 发件并验证 catch-all 收件。")
    parser.add_argument("--recipient", help="测试收件地址；缺省时自动生成一个新的 catch-all 别名")
    parser.add_argument("--poll-interval", type=float, help="轮询间隔（秒）")
    parser.add_argument("--timeout", type=float, help="最长等待时间（秒）")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        load_dotenv()
        config = load_config(args)
        recipient = args.recipient or new_test_address(config.domain)
        marker = secrets.token_urlsafe(8)

        print(f"检查 MailClaw 健康状态：{config.host}/api/health")
        request_json(config, "GET", "/api/health")
        print(f"发送测试邮件：{config.sender} → {recipient}")
        send_test_email(config, recipient, marker)
        print(f"开始轮询收件箱，最长等待 {config.timeout:.0f} 秒。")
        received = wait_for_email(config, recipient, marker)
        if not received:
            print(
                "未在时限内收到邮件。请检查 Email Routing 的 Catch-all 是否设置为 "
                "Send to a Worker → mailclaw，以及 MAILCLAW_FROM 是否已完成发信域验证。",
                file=sys.stderr,
            )
            return 2

        print("\n测试成功：邮件已发送并被 MailClaw 接收。")
        print(f"收件地址：{recipient}")
        print(f"邮件 ID：{received['id']}")
        print(f"主题：{received.get('subject', '')}")
        return 0
    except (MailClawError, ValueError) as error:
        print(f"测试失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

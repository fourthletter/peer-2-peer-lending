"""Send digest email via SMTP."""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} environment variable is required")
    return value


def send_digest(subject: str, plain_body: str, html_body: str) -> None:
    """Send multipart email (plain + HTML) to configured recipients."""
    host = _require_env("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = _require_env("SMTP_USER")
    password = _require_env("SMTP_PASSWORD")
    from_addr = os.environ.get("DIGEST_FROM_EMAIL", user).strip() or user
    to_addrs = [
        addr.strip()
        for addr in _require_env("DIGEST_TO_EMAIL").split(",")
        if addr.strip()
    ]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    logger.info("Sending digest to %s via %s:%d", to_addrs, host, port)
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(user, password)
        server.sendmail(from_addr, to_addrs, msg.as_string())

    logger.info("Digest email sent successfully")

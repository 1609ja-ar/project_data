"""Email sending behind an interface so SMTP can be swapped for another provider."""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings, get_settings

log = logging.getLogger("app.email")


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpEmailSender:
    def __init__(self, s: Settings):
        self.s = s

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.smtp_from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=15) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(msg)

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)


class DevConsoleEmailSender:
    """Development only: prints the email to the backend console. Never used in production."""

    async def send(self, to: str, subject: str, body: str) -> None:
        log.warning("DEV EMAIL (SMTP not configured) to=%s subject=%s\n%s", to, subject, body)


class DisabledEmailSender:
    async def send(self, to: str, subject: str, body: str) -> None:
        log.error("Email not sent: SMTP is not configured (subject=%s)", subject)


def get_email_sender() -> EmailSender:
    s = get_settings()
    if s.smtp_configured:
        return SmtpEmailSender(s)
    if s.app_env in ("development", "test"):
        return DevConsoleEmailSender()
    return DisabledEmailSender()

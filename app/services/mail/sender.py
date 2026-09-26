"""Sending email over SMTP (the system mailbox, TZ section 9, decision 1)."""

from collections.abc import Awaitable, Callable
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.config import Settings
from app.services.mail.auth import m365_access_token


class MailSendError(Exception):
    pass


class Sender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class SmtpSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _token_generator(self) -> Callable[[], Awaitable[str]] | None:
        if self.settings.smtp_auth != "oauth2":
            return None

        async def token() -> str:
            return await m365_access_token(self.settings)

        return token

    async def send(self, message: EmailMessage) -> None:
        s = self.settings
        password = s.smtp_password.get_secret_value() if s.smtp_auth == "password" else None
        try:
            await aiosmtplib.send(
                message,
                hostname=s.smtp_host,
                port=s.smtp_port,
                use_tls=s.smtp_ssl,
                start_tls=False if s.smtp_ssl else s.smtp_starttls,
                username=s.mail_address if s.smtp_auth != "none" else None,
                password=password,
                oauth_token_generator=self._token_generator(),
                timeout=s.smtp_timeout_seconds,
            )
        except (aiosmtplib.SMTPException, OSError) as exc:
            raise MailSendError(str(exc)) from exc

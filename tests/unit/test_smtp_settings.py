from email.message import EmailMessage
from typing import Any

import pytest

from app.config import Settings
from app.services.mail import sender as sender_module
from app.services.mail.sender import SmtpSender


async def test_mail_ru_uses_implicit_tls_and_password(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_send(message: EmailMessage, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(sender_module.aiosmtplib, "send", fake_send)
    settings = Settings(
        _env_file=None,
        mail_address="rd.company@mail.ru",
        smtp_host="smtp.mail.ru",
        smtp_port=465,
        smtp_ssl=True,
        smtp_starttls=True,  # ignored with implicit TLS
        smtp_auth="password",
        smtp_password="app-password",
    )

    await SmtpSender(settings).send(EmailMessage())

    [kwargs] = calls
    assert kwargs["hostname"] == "smtp.mail.ru"
    assert kwargs["port"] == 465
    assert kwargs["use_tls"] is True
    assert kwargs["start_tls"] is False
    assert kwargs["username"] == "rd.company@mail.ru"
    assert kwargs["password"] == "app-password"
    assert kwargs["oauth_token_generator"] is None

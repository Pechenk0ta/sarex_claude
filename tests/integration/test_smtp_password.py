"""SMTP password login, as with a Mail.ru app password (TZ section 9, decision 1)."""

import socket
from collections.abc import Iterator
from email.message import EmailMessage
from typing import Any

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

from app.config import Settings
from app.services.mail.sender import MailSendError, SmtpSender

APP_PASSWORD = "abcd efgh ijkl mnop"


class _Inbox:
    def __init__(self) -> None:
        self.count = 0

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        self.count += 1
        return "250 OK"


def _authenticator(server: Any, session: Any, envelope: Any, mechanism: str, data: Any) -> Any:
    ok = (
        isinstance(data, LoginPassword)
        and data.login == b"rd.company@mail.ru"
        and data.password == APP_PASSWORD.encode()
    )
    return AuthResult(success=ok)


@pytest.fixture
def server() -> Iterator[tuple[_Inbox, int]]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    inbox = _Inbox()
    controller = Controller(
        inbox,
        hostname="127.0.0.1",
        port=port,
        authenticator=_authenticator,
        auth_required=True,
        auth_require_tls=False,
    )
    controller.start()
    yield inbox, port
    controller.stop()


def _message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "rd.company@mail.ru"
    message["To"] = "pto@stroymonolit.ru"
    message["Subject"] = "Проверка"
    message.set_content("Текст")
    return message


def _settings(port: int, password: str) -> Settings:
    # The test server delays its answer to a wrong password; a short timeout keeps tests fast.
    return Settings(
        smtp_timeout_seconds=3,
        _env_file=None,
        mail_address="rd.company@mail.ru",
        smtp_host="127.0.0.1",
        smtp_port=port,
        smtp_auth="password",
        smtp_password=password,
    )


async def test_sends_with_app_password(server: tuple[_Inbox, int]) -> None:
    inbox, port = server
    await SmtpSender(_settings(port, APP_PASSWORD)).send(_message())
    assert inbox.count == 1


async def test_wrong_password_is_a_send_error(server: tuple[_Inbox, int]) -> None:
    inbox, port = server
    with pytest.raises(MailSendError):
        await SmtpSender(_settings(port, "wrong")).send(_message())
    assert inbox.count == 0

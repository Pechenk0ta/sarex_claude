import uuid
from datetime import date

from app.config import Settings
from app.services.ack_tokens import ack_url, make_ack_token, read_ack_token
from app.services.mail.letters import initial_letter, reply_address, to_email_message

SETTINGS = Settings(
    _env_file=None,
    mail_address="rd@company.ru",
    secret_key="k" * 32,
    app_base_url="https://rd.company.ru/",
)


def _letter(message: str | None) -> object:
    return initial_letter(
        SETTINGS,
        to="pto@stroymonolit.ru",
        reply_token="abc123",
        project="ЖК «Северная долина»",
        corpus="Корпус 2",
        sarex_link="https://sarex.example.ru/doc?x=1&y=2",
        message=message,
        deadline=date(2026, 10, 9),
        ack_url="https://rd.company.ru/ack/TOKEN",
        initiator="Смирнова Анна",
    )


def test_reply_address_uses_plus_token() -> None:
    assert reply_address(SETTINGS, "abc123") == "rd+abc123@company.ru"


def test_letter_contains_link_deadline_ack_and_message() -> None:
    letter = _letter("Обратите внимание на листы 12–14")
    assert letter.reply_to == "rd+abc123@company.ru"
    assert "09.10.2026" in letter.subject
    for part in (letter.text, letter.html):
        assert "https://rd.company.ru/ack/TOKEN" in part
        assert "листы 12–14" in part
    assert "Сообщение координатора" in letter.text
    assert letter.raw_content.startswith("Тема: ")


def test_letter_without_message_has_no_message_block() -> None:
    letter = _letter(None)
    assert "Сообщение координатора" not in letter.text
    assert "Сообщение координатора" not in letter.html


def test_html_is_escaped() -> None:
    letter = _letter("<script>alert(1)</script>")
    assert "<script>" not in letter.html
    assert "&lt;script&gt;" in letter.html
    assert "x=1&amp;y=2" in letter.html


def test_email_message_headers_and_parts() -> None:
    letter = _letter(None)
    message = to_email_message(
        SETTINGS,
        to=letter.to,
        subject=letter.subject,
        text=letter.text,
        html=letter.html,
        reply_to=letter.reply_to,
        message_id=letter.message_id,
    )
    assert message["Reply-To"] == "rd+abc123@company.ru"
    assert "rd@company.ru" in message["From"]
    assert message.get_body(("html",)) is not None
    assert message.get_body(("plain",)) is not None
    assert message["In-Reply-To"] is None


def test_reminder_continues_the_thread() -> None:
    letter = _letter(None)
    message = to_email_message(
        SETTINGS,
        to=letter.to,
        subject=letter.subject,
        text=letter.text,
        html=letter.html,
        reply_to=letter.reply_to,
        message_id="<new@company.ru>",
        in_reply_to="<first@company.ru>",
    )
    assert message["In-Reply-To"] == "<first@company.ru>"
    assert message["References"] == "<first@company.ru>"


def test_ack_token_roundtrip_and_tampering() -> None:
    notification_id = uuid.uuid4()
    token = make_ack_token(SETTINGS, notification_id)
    assert read_ack_token(SETTINGS, token) == notification_id
    # Change the first character: all its bits count (the signature's last one has ignored bits).
    tampered = ("J" if token[0] != "J" else "K") + token[1:]
    assert read_ack_token(SETTINGS, tampered) is None
    other = Settings(_env_file=None, secret_key="z" * 32)
    assert read_ack_token(other, token) is None
    assert ack_url(SETTINGS, notification_id).startswith("https://rd.company.ru/ack/")

"""Email texts (TZ section 6). Rendered once when a notification is created and stored in
the `sent` event, so the coordinator sees exactly what the contractor received."""

from dataclasses import dataclass
from datetime import date
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.config import Settings

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


@dataclass(frozen=True)
class Letter:
    to: str
    subject: str
    text: str
    html: str
    reply_to: str
    message_id: str

    @property
    def raw_content(self) -> str:
        """What the coordinator opens in the notification card."""
        return f"Тема: {self.subject}\nКому: {self.to}\n\n{self.text}"


def reply_address(settings: Settings, reply_token: str) -> str:
    """rd+<token>@domain: replies to it are matched to the notification (TZ 4.2)."""
    local, _, domain = settings.mail_address.partition("@")
    return f"{local}+{reply_token}@{domain}"


def initial_letter(
    settings: Settings,
    *,
    to: str,
    reply_token: str,
    project: str,
    corpus: str,
    sarex_link: str,
    message: str | None,
    deadline: date,
    ack_url: str,
    initiator: str,
) -> Letter:
    context = {
        "project": project,
        "corpus": corpus,
        "sarex_link": sarex_link,
        "message": message,
        "deadline": f"{deadline:%d.%m.%Y}",
        "ack_url": ack_url,
        "initiator": initiator,
    }
    domain = settings.mail_address.partition("@")[2] or "localhost"
    return Letter(
        to=to,
        subject=f"РД · {project}, {corpus} · подтвердите ознакомление до {deadline:%d.%m.%Y}",
        text=_env.get_template("initial.txt").render(context),
        html=_env.get_template("initial.html").render(context),
        reply_to=reply_address(settings, reply_token),
        message_id=make_msgid(domain=domain),
    )


def to_email_message(
    settings: Settings,
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    reply_to: str,
    message_id: str,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = Address(settings.mail_display_name, addr_spec=settings.mail_address)
    message["To"] = to
    message["Reply-To"] = reply_to
    message["Subject"] = subject
    message["Message-ID"] = message_id
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message

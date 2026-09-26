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
    reminder: bool = False,
) -> Letter:
    """The notification to a contractor; `reminder` marks the repeated one (TZ 6, 1–2)."""
    context = {
        "project": project,
        "corpus": corpus,
        "sarex_link": sarex_link,
        "message": message,
        "deadline": f"{deadline:%d.%m.%Y}",
        "ack_url": ack_url,
        "initiator": initiator,
        "reminder": reminder,
    }
    domain = settings.mail_address.partition("@")[2] or "localhost"
    subject = f"РД · {project}, {corpus} · подтвердите ознакомление до {deadline:%d.%m.%Y}"
    return Letter(
        to=to,
        subject=f"Повторно: {subject}" if reminder else subject,
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
    in_reply_to: str | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = Address(settings.mail_display_name, addr_spec=settings.mail_address)
    message["To"] = to
    message["Reply-To"] = reply_to
    message["Subject"] = subject
    message["Message-ID"] = message_id
    message["Date"] = formatdate(localtime=False, usegmt=True)
    if in_reply_to:
        # Reminders continue the thread of the first letter in the contractor's mailbox.
        message["In-Reply-To"] = in_reply_to
        message["References"] = in_reply_to
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def rejection_letter(
    settings: Settings,
    *,
    to: list[str],
    project: str,
    corpus: str,
    contractor: str,
    sarex_link: str,
    sent_on: date,
    reply_text: str,
    card_url: str,
) -> Letter:
    """«РД не принята» to the initiator and the project manager (TZ 4.2, section 6 template 5)."""
    context = {
        "project": project,
        "corpus": corpus,
        "contractor": contractor,
        "sarex_link": sarex_link,
        "sent_on": f"{sent_on:%d.%m.%Y}",
        "reply_text": reply_text,
        "card_url": card_url,
    }
    domain = settings.mail_address.partition("@")[2] or "localhost"
    return Letter(
        to=", ".join(dict.fromkeys(to)),
        subject=f"РД не принята · {contractor} · {project}, {corpus}",
        text=_env.get_template("rejection.txt").render(context),
        html=_env.get_template("rejection.html").render(context),
        reply_to=settings.mail_address,
        message_id=make_msgid(domain=domain),
    )


@dataclass(frozen=True)
class OverdueItem:
    contractor: str
    email: str
    workdays_without_answer: int
    card_url: str


def escalation_letter(
    settings: Settings,
    *,
    to: str,
    project: str,
    corpus: str,
    sarex_link: str,
    sent_on: date,
    deadline: date,
    items: list[OverdueItem],
    initiator: str,
) -> Letter:
    """To the project manager when the deadline passed without an answer (TZ 4.3, 6.3).

    One letter per mailing lists every contractor who has not answered.
    """
    context = {
        "project": project,
        "corpus": corpus,
        "sarex_link": sarex_link,
        "sent_on": f"{sent_on:%d.%m.%Y}",
        "deadline": f"{deadline:%d.%m.%Y}",
        "items": items,
        "initiator": initiator,
    }
    domain = settings.mail_address.partition("@")[2] or "localhost"
    count = len(items)
    who = items[0].contractor if count == 1 else f"{count} подрядчиков"
    return Letter(
        to=to,
        subject=f"Эскалация: нет подтверждения РД · {project}, {corpus} · {who}",
        text=_env.get_template("escalation.txt").render(context),
        html=_env.get_template("escalation.html").render(context),
        reply_to=settings.mail_address,
        message_id=make_msgid(domain=domain),
    )

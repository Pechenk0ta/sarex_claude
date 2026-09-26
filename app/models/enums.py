"""Enumerations from section 3 of the TZ, stored as strings with a CHECK constraint."""

from enum import StrEnum

import sqlalchemy as sa


class Channel(StrEnum):
    EMAIL = "email"
    TELEGRAM = "telegram"


class NotificationStatus(StrEnum):
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    HAS_QUESTIONS = "has_questions"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class AiCategory(StrEnum):
    ACKNOWLEDGEMENT = "acknowledgement"
    QUESTION = "question"
    OBJECTION = "objection"
    REJECTION = "rejection"
    UNCLEAR = "unclear"


class EventType(StrEnum):
    SENT = "sent"
    REMINDER_1 = "reminder_1"
    REMINDER_3 = "reminder_3"
    REPLY_ACK = "reply_ack"
    REPLY_QUESTION = "reply_question"
    REPLY_REJECTION = "reply_rejection"
    REPLY_UNCLEAR = "reply_unclear"
    REJECTION_NOTIFIED = "rejection_notified"
    ESCALATED = "escalated"
    CATEGORY_OVERRIDDEN = "category_overridden"
    STATUS_CHANGED = "status_changed"
    DEADLINE_CHANGED = "deadline_changed"


class UserRole(StrEnum):
    COORDINATOR = "coordinator"
    ADMIN = "admin"


def str_enum(enum_cls: type[StrEnum], name: str) -> sa.Enum:
    """VARCHAR + CHECK instead of a native PG enum: new values need no ALTER TYPE."""
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )

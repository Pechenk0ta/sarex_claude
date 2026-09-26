import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk
from app.models.enums import (
    AiCategory,
    Channel,
    EventType,
    NotificationStatus,
    str_enum,
)


class Notification(UUIDPk, Timestamps, Base):
    """One contractor's notification within a mailing, TZ 3.4.

    A mailing is all notifications with the same `corpus_id` and `sarex_link` (TZ 4.1).
    Status changes go through `app.services.notifications` only.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        sa.Index("ix_notifications_mailing", "corpus_id", "sarex_link"),
        sa.Index("ix_notifications_status_sent_at", "status", "sent_at"),
        sa.CheckConstraint("reminder_count BETWEEN 0 AND 2", name="reminder_count_range"),
        sa.CheckConstraint(
            "ai_confidence IS NULL OR ai_confidence BETWEEN 0 AND 1",
            name="ai_confidence_range",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    corpus_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("corpuses.id"))
    contractor_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("contractors.id"), index=True)
    sarex_link: Mapped[str] = mapped_column(sa.String(2000))
    reply_token: Mapped[str] = mapped_column(sa.String(64), unique=True)
    initiator_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    channel: Mapped[Channel] = mapped_column(
        str_enum(Channel, "channel"), server_default=Channel.EMAIL.value
    )
    status: Mapped[NotificationStatus] = mapped_column(
        str_enum(NotificationStatus, "notification_status"),
        server_default=NotificationStatus.SENT.value,
    )
    ai_category: Mapped[AiCategory | None] = mapped_column(str_enum(AiCategory, "ai_category"))
    ai_confidence: Mapped[float | None]
    sent_at: Mapped[datetime]
    deadline_at: Mapped[datetime]
    acknowledged_at: Mapped[datetime | None]
    rejected_at: Mapped[datetime | None]
    last_reminder_at: Mapped[datetime | None]
    reminder_count: Mapped[int] = mapped_column(server_default="0")
    escalated_at: Mapped[datetime | None]
    message: Mapped[str | None] = mapped_column(sa.Text)
    needs_manual_review: Mapped[bool] = mapped_column(server_default=sa.false())

    events: Mapped[list["NotificationEvent"]] = relationship(
        back_populates="notification", order_by="NotificationEvent.created_at"
    )


class NotificationEvent(UUIDPk, Base):
    """History of a notification: every outgoing and incoming message, TZ 3.5."""

    __tablename__ = "notification_events"
    __table_args__ = (
        sa.Index("ix_notification_events_notification_created", "notification_id", "created_at"),
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("notifications.id", ondelete="CASCADE")
    )
    type: Mapped[EventType] = mapped_column(str_enum(EventType, "event_type"))
    channel: Mapped[Channel] = mapped_column(
        str_enum(Channel, "channel"), server_default=Channel.EMAIL.value
    )
    raw_content: Mapped[str] = mapped_column(sa.Text, server_default="")
    ai_category: Mapped[AiCategory | None] = mapped_column(str_enum(AiCategory, "ai_category"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sa.text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=sa.func.now())

    notification: Mapped[Notification] = relationship(back_populates="events")

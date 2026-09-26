"""event types for manual status and deadline changes

Revision ID: 1e5041e28c1a
Revises: d187a1fe07f3
Create Date: 2026-09-26 15:20:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1e5041e28c1a"
down_revision: str | Sequence[str] | None = "d187a1fe07f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = [
    "sent",
    "reminder_1",
    "reminder_3",
    "reply_ack",
    "reply_question",
    "reply_rejection",
    "reply_unclear",
    "rejection_notified",
    "escalated",
    "category_overridden",
]
NEW = [*OLD, "status_changed", "deadline_changed"]
NAME = "ck_notification_events_event_type"


def _check(values: list[str]) -> str:
    return "type IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """Autogenerate does not see CHECK changes: the enum CHECK is replaced by hand."""
    op.execute(f"ALTER TABLE notification_events DROP CONSTRAINT {NAME}")
    op.execute(f"ALTER TABLE notification_events ADD CONSTRAINT {NAME} CHECK ({_check(NEW)})")


def downgrade() -> None:
    op.execute(
        "DELETE FROM notification_events WHERE type IN ('status_changed', 'deadline_changed')"
    )
    op.execute(f"ALTER TABLE notification_events DROP CONSTRAINT {NAME}")
    op.execute(f"ALTER TABLE notification_events ADD CONSTRAINT {NAME} CHECK ({_check(OLD)})")

"""initial schema: tables from TZ section 3

Revision ID: 52dc986e086d
Revises:
Create Date: 2026-09-26 10:45:43.282725

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "52dc986e086d"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Enum columns are VARCHAR + CHECK: the CHECK comes from sa.Enum(create_constraint=True).
    Autogenerate also emitted duplicate explicit CheckConstraints for them; removed by hand.
    """
    op.create_table(
        "contractors",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contractors")),
        sa.UniqueConstraint("email", name=op.f("uq_contractors_email")),
        sa.UniqueConstraint("name", name=op.f("uq_contractors_name")),
    )
    op.create_table(
        "holidays",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("is_workday", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("date", name=op.f("pk_holidays")),
    )
    op.create_table(
        "projects",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("project_manager_email", sa.String(length=320), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("name", name=op.f("uq_projects_name")),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column(
            "role",
            sa.Enum(
                "coordinator",
                "admin",
                name="user_role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "corpuses",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_corpuses_project_id_projects")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corpuses")),
        sa.UniqueConstraint("project_id", "name", name="uq_corpuses_project_name"),
    )
    op.create_index(op.f("ix_corpuses_project_id"), "corpuses", ["project_id"], unique=False)
    op.create_table(
        "project_contractors",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("contractor_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["contractor_id"],
            ["contractors.id"],
            name=op.f("fk_project_contractors_contractor_id_contractors"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_contractors_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id", "contractor_id", name=op.f("pk_project_contractors")),
    )
    op.create_index(
        op.f("ix_project_contractors_contractor_id"),
        "project_contractors",
        ["contractor_id"],
        unique=False,
    )
    op.create_table(
        "notifications",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("corpus_id", sa.Uuid(), nullable=False),
        sa.Column("contractor_id", sa.Uuid(), nullable=False),
        sa.Column("sarex_link", sa.String(length=2000), nullable=False),
        sa.Column("reply_token", sa.String(length=64), nullable=False),
        sa.Column("initiator_id", sa.Uuid(), nullable=False),
        sa.Column(
            "channel",
            sa.Enum(
                "email",
                "telegram",
                name="channel",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="email",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "sent",
                "acknowledged",
                "has_questions",
                "rejected",
                "escalated",
                name="notification_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="sent",
            nullable=False,
        ),
        sa.Column(
            "ai_category",
            sa.Enum(
                "acknowledgement",
                "question",
                "objection",
                "rejection",
                "unclear",
                name="ai_category",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("ai_confidence", sa.Double(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "needs_manual_review", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ai_confidence IS NULL OR ai_confidence BETWEEN 0 AND 1",
            name=op.f("ck_notifications_ai_confidence_range"),
        ),
        sa.CheckConstraint(
            "reminder_count BETWEEN 0 AND 2", name=op.f("ck_notifications_reminder_count_range")
        ),
        sa.ForeignKeyConstraint(
            ["contractor_id"],
            ["contractors.id"],
            name=op.f("fk_notifications_contractor_id_contractors"),
        ),
        sa.ForeignKeyConstraint(
            ["corpus_id"], ["corpuses.id"], name=op.f("fk_notifications_corpus_id_corpuses")
        ),
        sa.ForeignKeyConstraint(
            ["initiator_id"], ["users.id"], name=op.f("fk_notifications_initiator_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_notifications_project_id_projects")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("reply_token", name=op.f("uq_notifications_reply_token")),
    )
    op.create_index(
        op.f("ix_notifications_contractor_id"), "notifications", ["contractor_id"], unique=False
    )
    op.create_index(
        "ix_notifications_mailing", "notifications", ["corpus_id", "sarex_link"], unique=False
    )
    op.create_index(
        op.f("ix_notifications_project_id"), "notifications", ["project_id"], unique=False
    )
    op.create_index(
        "ix_notifications_status_sent_at", "notifications", ["status", "sent_at"], unique=False
    )
    op.create_table(
        "notification_events",
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
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
                name="event_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "channel",
            sa.Enum(
                "email",
                "telegram",
                name="channel",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="email",
            nullable=False,
        ),
        sa.Column("raw_content", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "ai_category",
            sa.Enum(
                "acknowledgement",
                "question",
                "objection",
                "rejection",
                "unclear",
                name="ai_category",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            name=op.f("fk_notification_events_notification_id_notifications"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_events")),
    )
    op.create_index(
        "ix_notification_events_notification_created",
        "notification_events",
        ["notification_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_notification_events_notification_created", table_name="notification_events")
    op.drop_table("notification_events")
    op.drop_index("ix_notifications_status_sent_at", table_name="notifications")
    op.drop_index(op.f("ix_notifications_project_id"), table_name="notifications")
    op.drop_index("ix_notifications_mailing", table_name="notifications")
    op.drop_index(op.f("ix_notifications_contractor_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_project_contractors_contractor_id"), table_name="project_contractors")
    op.drop_table("project_contractors")
    op.drop_index(op.f("ix_corpuses_project_id"), table_name="corpuses")
    op.drop_table("corpuses")
    op.drop_table("users")
    op.drop_table("projects")
    op.drop_table("holidays")
    op.drop_table("contractors")

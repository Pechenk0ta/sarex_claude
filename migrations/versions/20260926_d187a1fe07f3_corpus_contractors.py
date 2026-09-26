"""contractors are assigned to corpuses instead of projects

Revision ID: d187a1fe07f3
Revises: 52dc986e086d
Create Date: 2026-09-26 14:55:54.980387

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d187a1fe07f3"
down_revision: str | Sequence[str] | None = "52dc986e086d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace project_contractors with corpus_contractors.

    Existing links are kept: a contractor of a project is assigned to every corpus of it,
    so nobody stops receiving mailings; the administrator narrows the lists afterwards.
    """
    op.create_table(
        "corpus_contractors",
        sa.Column("corpus_id", sa.Uuid(), nullable=False),
        sa.Column("contractor_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["contractor_id"],
            ["contractors.id"],
            name=op.f("fk_corpus_contractors_contractor_id_contractors"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["corpus_id"],
            ["corpuses.id"],
            name=op.f("fk_corpus_contractors_corpus_id_corpuses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("corpus_id", "contractor_id", name=op.f("pk_corpus_contractors")),
    )
    op.create_index(
        op.f("ix_corpus_contractors_contractor_id"),
        "corpus_contractors",
        ["contractor_id"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO corpus_contractors (corpus_id, contractor_id)
        SELECT c.id, pc.contractor_id
        FROM project_contractors pc JOIN corpuses c ON c.project_id = pc.project_id
        """
    )
    op.drop_index(op.f("ix_project_contractors_contractor_id"), table_name="project_contractors")
    op.drop_table("project_contractors")


def downgrade() -> None:
    """Back to project_contractors: a contractor of any corpus joins its project."""
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
    op.execute(
        """
        INSERT INTO project_contractors (project_id, contractor_id)
        SELECT DISTINCT c.project_id, cc.contractor_id
        FROM corpus_contractors cc JOIN corpuses c ON c.id = cc.corpus_id
        """
    )
    op.drop_index(op.f("ix_corpus_contractors_contractor_id"), table_name="corpus_contractors")
    op.drop_table("corpus_contractors")

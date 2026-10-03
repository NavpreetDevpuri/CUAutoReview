"""Login throttling: failed sign-ins keyed by hashed email+client and client address.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("pair_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_login_attempts_created_at"), "login_attempts", ["created_at"], unique=False)
    op.create_index("ix_login_attempts_ip_created", "login_attempts", ["ip_hash", "created_at"], unique=False)
    op.create_index("ix_login_attempts_pair_created", "login_attempts", ["pair_hash", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_login_attempts_pair_created", table_name="login_attempts")
    op.drop_index("ix_login_attempts_ip_created", table_name="login_attempts")
    op.drop_index(op.f("ix_login_attempts_created_at"), table_name="login_attempts")
    op.drop_table("login_attempts")

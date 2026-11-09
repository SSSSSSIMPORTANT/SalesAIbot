"""add conversation suggestion pause

Revision ID: f7e630a2c945
Revises: ed29a8405bf3
"""

from alembic import op
import sqlalchemy as sa


revision = "f7e630a2c945"
down_revision = "ed29a8405bf3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("suggestions_paused", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("suggestions_paused")

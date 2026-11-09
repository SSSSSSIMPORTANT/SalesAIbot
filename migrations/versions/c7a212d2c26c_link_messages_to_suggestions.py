"""link messages to suggestions

Revision ID: c7a212d2c26c
Revises: 941f4292c4e2
Create Date: 2026-11-07 15:58:14.130303

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a212d2c26c'
down_revision: Union[str, Sequence[str], None] = '941f4292c4e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(
            sa.Column("source_suggestion_id", sa.String(32), nullable=True)
        )
        batch_op.add_column(
            sa.Column("adoption_mode", sa.String(16), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_messages_source_suggestion_id",
            "reply_suggestions",
            ["source_suggestion_id"],
            ["id"],
        )
        batch_op.create_check_constraint(
            "ck_messages_suggestion_adoption",
            "(source_suggestion_id IS NULL AND adoption_mode IS NULL) OR "
            "(source_suggestion_id IS NOT NULL AND actor = 'human' "
            "AND adoption_mode IS NOT NULL "
            "AND adoption_mode IN ('verbatim', 'edited'))",
        )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_constraint(
            "ck_messages_suggestion_adoption", type_="check"
        )
        batch_op.drop_constraint(
            "fk_messages_source_suggestion_id", type_="foreignkey"
        )
        batch_op.drop_column("adoption_mode")
        batch_op.drop_column("source_suggestion_id")

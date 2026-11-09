"""add fact revocation

Revision ID: 3cb11803cb87
Revises: adf0b1470683
Create Date: 2026-11-02 16:37:54.117973

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3cb11803cb87'
down_revision: Union[str, Sequence[str], None] = 'adf0b1470683'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_facts") as batch_op:
        batch_op.add_column(
            sa.Column("revoked_at", sa.String(40), nullable=True)
        )
        batch_op.drop_constraint(
            "ck_conversation_facts_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_conversation_facts_status",
            "status IN ('confirmed', 'superseded', 'revoked')",
        )


def downgrade() -> None:
    connection = op.get_bind()
    revoked_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM conversation_facts "
            "WHERE status = 'revoked'"
        )
    )

    if revoked_count:
        raise RuntimeError(
            "Cannot downgrade while revoked facts exist"
        )

    with op.batch_alter_table("conversation_facts") as batch_op:
        batch_op.drop_constraint(
            "ck_conversation_facts_status",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_conversation_facts_status",
            "status IN ('confirmed', 'superseded')",
        )
        batch_op.drop_column("revoked_at")

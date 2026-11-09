"""add operator ownership to customers and conversations

Revision ID: ed29a8405bf3
Revises: f15f43a168af
"""

from alembic import op
import sqlalchemy as sa


revision = "ed29a8405bf3"
down_revision = "f15f43a168af"
branch_labels = None
depends_on = None


def _begin_sqlite_batch_transaction() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite" and not op.get_context().as_sql:
        # The sqlite3 driver's legacy mode does not begin a transaction for DDL.
        # Keep both table rebuilds and the revision update in one transaction.
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin_sqlite_batch_transaction()
    with op.batch_alter_table("customers") as batch:
        batch.add_column(sa.Column("owner_operator_id", sa.String(32), nullable=True))
        batch.create_foreign_key(
            "fk_customers_owner_operator", "operator_accounts", ["owner_operator_id"], ["id"]
        )
        batch.create_unique_constraint("uq_customers_id_owner", ["id", "owner_operator_id"])
        batch.create_index("ix_customers_owner_operator_id", ["owner_operator_id"])

    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("owner_operator_id", sa.String(32), nullable=True))
        batch.create_foreign_key(
            "fk_conversations_owner_operator", "operator_accounts", ["owner_operator_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_conversations_customer_owner",
            "customers",
            ["customer_id", "owner_operator_id"],
            ["id", "owner_operator_id"],
        )
        batch.create_index("ix_conversations_owner_operator_id", ["owner_operator_id"])


def downgrade() -> None:
    _begin_sqlite_batch_transaction()
    with op.batch_alter_table("conversations") as batch:
        batch.drop_index("ix_conversations_owner_operator_id")
        batch.drop_constraint("fk_conversations_customer_owner", type_="foreignkey")
        batch.drop_constraint("fk_conversations_owner_operator", type_="foreignkey")
        batch.drop_column("owner_operator_id")

    with op.batch_alter_table("customers") as batch:
        batch.drop_index("ix_customers_owner_operator_id")
        batch.drop_constraint("uq_customers_id_owner", type_="unique")
        batch.drop_constraint("fk_customers_owner_operator", type_="foreignkey")
        batch.drop_column("owner_operator_id")

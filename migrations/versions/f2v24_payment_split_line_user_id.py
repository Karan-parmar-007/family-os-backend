"""Add user_id to payment_split_lines for PERSONAL pool splits."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2v24paymentsplituserid"
down_revision: Union[str, Sequence[str], None] = "f2v23canonicaldebtsystem"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("payment_split_lines")}
    fks = {fk["name"] for fk in inspector.get_foreign_keys("payment_split_lines")}

    if "user_id" not in columns:
        op.add_column(
            "payment_split_lines",
            sa.Column("user_id", sa.UUID(), nullable=True),
        )
    if "fk_payment_split_lines_user_id" not in fks:
        op.create_foreign_key(
            "fk_payment_split_lines_user_id",
            "payment_split_lines",
            "users",
            ["user_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("payment_split_lines")}
    fks = {fk["name"] for fk in inspector.get_foreign_keys("payment_split_lines")}

    if "fk_payment_split_lines_user_id" in fks:
        op.drop_constraint(
            "fk_payment_split_lines_user_id", "payment_split_lines", type_="foreignkey"
        )
    if "user_id" in columns:
        op.drop_column("payment_split_lines", "user_id")

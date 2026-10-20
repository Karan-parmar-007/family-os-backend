"""Vault secrets move to AES-GCM; membership and connection indexes.

- Existing XOR-encoded vault secrets are re-encrypted with AES-GCM ("v2:" prefix).
- user_family_links is looked up by family (members, heads) but only had the
  (user_id, family_id) primary key.
- Active family connections are looked up by pair.
- ix_notifications_user_id is covered by ix_notifications_user_time.

Revision ID: fos012_vault_aes_idx
Revises: fos011_transfers_v3
Create Date: 2026-10-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fos012_vault_aes_idx"
down_revision: Union[str, None] = "fos011_transfers_v3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.api.routes.vault.vault_service import _AES_PREFIX, _encrypt_secret, _legacy_xor

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, ciphertext FROM fos_vault_items WHERE ciphertext IS NOT NULL")
    ).all()
    for item_id, ciphertext in rows:
        if ciphertext.startswith(_AES_PREFIX):
            continue
        bind.execute(
            sa.text("UPDATE fos_vault_items SET ciphertext = :c WHERE id = :i"),
            {"c": _encrypt_secret(_legacy_xor(ciphertext)), "i": item_id},
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_family_links_family ON user_family_links (family_id, is_family_manager)"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_family_relationships_active_pair
        ON family_relationships (family_a_id, family_b_id) WHERE status = 'ACTIVE'
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_notifications_user_id")


def downgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications (user_id)")
    op.execute("DROP INDEX IF EXISTS ix_family_relationships_active_pair")
    op.execute("DROP INDEX IF EXISTS ix_user_family_links_family")
    # AES secrets stay readable after downgrade: _decrypt_secret handles both formats.

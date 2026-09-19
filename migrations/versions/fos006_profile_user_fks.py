"""Point identity FKs at fos_profiles instead of legacy users.

Revision ID: fos006_profile_fks
Revises: fos005_emi_remaining
Create Date: 2026-09-09
"""
from typing import Sequence, Union

from alembic import op

revision: str = "fos006_profile_fks"
down_revision: Union[str, None] = "fos005_emi_remaining"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE r RECORD;
        BEGIN
          IF to_regclass('public.users') IS NULL THEN
            RETURN;
          END IF;
          FOR r IN
            SELECT conrelid::regclass AS tbl, conname
            FROM pg_constraint
            WHERE contype = 'f'
              AND confrelid = 'users'::regclass
          LOOP
            EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', r.tbl, r.conname);
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # Legacy users FKs are not restored; fos_profiles is the identity table.
    pass

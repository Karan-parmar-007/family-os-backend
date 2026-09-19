"""Retire legacy debt tables after canonical debt migration."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f2v26droplegacydebts"
down_revision: Union[str, Sequence[str], None] = "f2v25debtpayerobligations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _assert_all_references_resolve(bind: sa.Connection) -> None:
    unresolved_jobs = bind.scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM scheduled_jobs sj
            WHERE sj.source_type IN ('FAMILY_DEBT', 'PERSONAL_DEBT')
              AND NOT EXISTS (
                SELECT 1
                FROM debts d
                WHERE d.id = sj.source_id
                   OR (
                     sj.source_type = 'FAMILY_DEBT'
                     AND d.legacy_family_debt_id = sj.source_id
                   )
                   OR (
                     sj.source_type = 'PERSONAL_DEBT'
                     AND d.legacy_personal_debt_id = sj.source_id
                   )
              )
            """
        )
    )
    unresolved_plans = bind.scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM payment_split_plans p
            WHERE p.entity_type IN ('FAMILY_DEBT', 'PERSONAL_DEBT')
              AND NOT EXISTS (
                SELECT 1
                FROM debts d
                WHERE d.id = p.entity_id
                   OR (
                     p.entity_type = 'FAMILY_DEBT'
                     AND d.legacy_family_debt_id = p.entity_id
                   )
                   OR (
                     p.entity_type = 'PERSONAL_DEBT'
                     AND d.legacy_personal_debt_id = p.entity_id
                   )
              )
            """
        )
    )
    if unresolved_jobs or unresolved_plans:
        raise RuntimeError(
            "Cannot drop legacy debts: "
            f"{unresolved_jobs or 0} scheduled jobs and "
            f"{unresolved_plans or 0} split plans have no canonical debt"
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    scope_columns = {column["name"] for column in inspector.get_columns("debt_scope_views")}
    if "excluded" not in scope_columns:
        op.add_column(
            "debt_scope_views",
            sa.Column(
                "excluded",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
        )

    _assert_all_references_resolve(bind)

    # Canonical IDs normally equal the legacy ID. The correlated lookup handles
    # the collision case where a personal debt had to receive a new UUID.
    op.execute(
        sa.text(
            """
            UPDATE scheduled_jobs sj
            SET source_id = (
                  SELECT d.id
                  FROM debts d
                  WHERE d.id = sj.source_id
                     OR (
                       sj.source_type = 'FAMILY_DEBT'
                       AND d.legacy_family_debt_id = sj.source_id
                     )
                     OR (
                       sj.source_type = 'PERSONAL_DEBT'
                       AND d.legacy_personal_debt_id = sj.source_id
                     )
                  ORDER BY CASE
                    WHEN sj.source_type = 'FAMILY_DEBT'
                     AND d.legacy_family_debt_id = sj.source_id THEN 0
                    WHEN sj.source_type = 'PERSONAL_DEBT'
                     AND d.legacy_personal_debt_id = sj.source_id THEN 0
                    ELSE 1
                  END
                  LIMIT 1
                ),
                source_type = 'DEBT'
            WHERE sj.source_type IN ('FAMILY_DEBT', 'PERSONAL_DEBT')
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE payment_split_plans p
            SET entity_id = (
                  SELECT d.id
                  FROM debts d
                  WHERE d.id = p.entity_id
                     OR (
                       p.entity_type = 'FAMILY_DEBT'
                       AND d.legacy_family_debt_id = p.entity_id
                     )
                     OR (
                       p.entity_type = 'PERSONAL_DEBT'
                       AND d.legacy_personal_debt_id = p.entity_id
                     )
                  ORDER BY CASE
                    WHEN p.entity_type = 'FAMILY_DEBT'
                     AND d.legacy_family_debt_id = p.entity_id THEN 0
                    WHEN p.entity_type = 'PERSONAL_DEBT'
                     AND d.legacy_personal_debt_id = p.entity_id THEN 0
                    ELSE 1
                  END
                  LIMIT 1
                ),
                entity_type = 'DEBT'
            WHERE p.entity_type IN ('FAMILY_DEBT', 'PERSONAL_DEBT')
            """
        )
    )

    # Preserve per-user legacy family access as viewer-specific FAMILY scope
    # overrides. The family list prefers these over the generic family view.
    op.execute(
        sa.text(
            """
            UPDATE debt_scope_views view
            SET access_level = a.access_level,
                updated_at = a.updated_at
            FROM personal_debt_access a
            JOIN debts d ON d.legacy_personal_debt_id = a.debt_id
            WHERE view.debt_id = d.id
              AND view.scope_kind = 'PERSONAL'
              AND view.user_id = a.user_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO debt_scope_views (
                id, debt_id, scope_kind, family_id, user_id, is_primary,
                display_name, display_type, display_total_amount,
                display_remaining_amount, display_emi_amount,
                display_interest_rate, is_masked, show_breakdown,
                access_level, excluded, created_at, updated_at
            )
            SELECT
                gen_random_uuid(), d.id, 'FAMILY', d.primary_family_id,
                a.user_id, false,
                COALESCE(base.display_name, d.debt_name),
                COALESCE(base.display_type, d.type),
                COALESCE(base.display_total_amount, d.total_amount),
                COALESCE(base.display_remaining_amount, d.remaining_amount),
                COALESCE(base.display_emi_amount, d.emi_amount),
                COALESCE(base.display_interest_rate, d.interest_rate),
                COALESCE(base.is_masked, false),
                COALESCE(base.show_breakdown, false),
                a.access_level, false, a.created_at, a.updated_at
            FROM family_debt_access a
            JOIN debts d ON d.legacy_family_debt_id = a.debt_id
            LEFT JOIN debt_scope_views base
              ON base.debt_id = d.id
             AND base.scope_kind = 'FAMILY'
             AND base.family_id = d.primary_family_id
             AND base.user_id IS NULL
            WHERE NOT EXISTS (
                SELECT 1
                FROM debt_scope_views existing
                WHERE existing.debt_id = d.id
                  AND existing.scope_kind = 'FAMILY'
                  AND existing.family_id IS NOT DISTINCT FROM d.primary_family_id
                  AND existing.user_id IS NOT DISTINCT FROM a.user_id
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE debt_scope_views view
            SET access_level = a.access_level,
                updated_at = a.updated_at
            FROM family_debt_access a
            JOIN debts d ON d.legacy_family_debt_id = a.debt_id
            WHERE view.debt_id = d.id
              AND view.scope_kind = 'FAMILY'
              AND view.family_id IS NOT DISTINCT FROM d.primary_family_id
              AND view.user_id IS NOT DISTINCT FROM a.user_id
            """
        )
    )

    # Personal access becomes a personal scope view for the selected user.
    op.execute(
        sa.text(
            """
            INSERT INTO debt_scope_views (
                id, debt_id, scope_kind, family_id, user_id, is_primary,
                display_name, display_type, display_total_amount,
                display_remaining_amount, display_emi_amount,
                display_interest_rate, is_masked, show_breakdown,
                access_level, excluded, created_at, updated_at
            )
            SELECT
                gen_random_uuid(), d.id, 'PERSONAL', NULL, a.user_id, false,
                COALESCE(base.display_name, d.debt_name),
                COALESCE(base.display_type, d.type),
                COALESCE(base.display_total_amount, d.total_amount),
                COALESCE(base.display_remaining_amount, d.remaining_amount),
                COALESCE(base.display_emi_amount, d.emi_amount),
                COALESCE(base.display_interest_rate, d.interest_rate),
                COALESCE(base.is_masked, false),
                COALESCE(base.show_breakdown, true),
                a.access_level, false, a.created_at, a.updated_at
            FROM personal_debt_access a
            JOIN debts d ON d.legacy_personal_debt_id = a.debt_id
            LEFT JOIN debt_scope_views base
              ON base.debt_id = d.id
             AND base.scope_kind = 'PERSONAL'
             AND base.user_id = d.owner_user_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM debt_scope_views existing
                WHERE existing.debt_id = d.id
                  AND existing.scope_kind = 'PERSONAL'
                  AND existing.user_id = a.user_id
            )
            """
        )
    )

    # Exclusions are per viewer, so keep them on viewer-specific family views
    # instead of hiding the debt from the entire family.
    op.execute(
        sa.text(
            """
            INSERT INTO debt_scope_views (
                id, debt_id, scope_kind, family_id, user_id, is_primary,
                display_name, display_type, display_total_amount,
                display_remaining_amount, display_emi_amount,
                display_interest_rate, is_masked, show_breakdown,
                access_level, excluded, created_at, updated_at
            )
            SELECT
                gen_random_uuid(), d.id, 'FAMILY', d.primary_family_id,
                x.user_id, false,
                COALESCE(base.display_name, d.debt_name),
                COALESCE(base.display_type, d.type),
                COALESCE(base.display_total_amount, d.total_amount),
                COALESCE(base.display_remaining_amount, d.remaining_amount),
                COALESCE(base.display_emi_amount, d.emi_amount),
                COALESCE(base.display_interest_rate, d.interest_rate),
                COALESCE(base.is_masked, false),
                COALESCE(base.show_breakdown, false),
                COALESCE(base.access_level, 'FAMILY'),
                true, x.created_at, x.updated_at
            FROM exclude_from_family_debts x
            JOIN debts d ON d.legacy_family_debt_id = x.debt_id
            LEFT JOIN debt_scope_views base
              ON base.debt_id = d.id
             AND base.scope_kind = 'FAMILY'
             AND base.family_id = d.primary_family_id
             AND base.user_id IS NULL
            WHERE NOT EXISTS (
                SELECT 1
                FROM debt_scope_views existing
                WHERE existing.debt_id = d.id
                  AND existing.scope_kind = 'FAMILY'
                  AND existing.family_id IS NOT DISTINCT FROM d.primary_family_id
                  AND existing.user_id IS NOT DISTINCT FROM x.user_id
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE debt_scope_views view
            SET excluded = true,
                updated_at = x.updated_at
            FROM exclude_from_family_debts x
            JOIN debts d ON d.legacy_family_debt_id = x.debt_id
            WHERE view.debt_id = d.id
              AND view.scope_kind = 'FAMILY'
              AND view.family_id IS NOT DISTINCT FROM d.primary_family_id
              AND view.user_id IS NOT DISTINCT FROM x.user_id
            """
        )
    )

    for table_name in (
        "family_debt_access",
        "personal_debt_access",
        "exclude_from_family_debts",
        "family_debts",
        "personal_debts",
    ):
        op.drop_table(table_name)

    op.drop_column("debts", "legacy_family_debt_id")
    op.drop_column("debts", "legacy_personal_debt_id")


def downgrade() -> None:
    raise NotImplementedError("Legacy debt tables cannot be reconstructed")

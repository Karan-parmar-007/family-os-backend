from decimal import Decimal

import pytest

from app.core.constants import LEDGER_IN, LEDGER_OUT, LEDGER_SOURCE_MANUAL, POOL_FAMILY
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef


@pytest.mark.integration
async def test_ledger_apply_movement_updates_family_cache(db_session, any_family_id):
    ledger = SavingsLedgerService(db_session)
    pool = SavingsPoolRef(pool_type=POOL_FAMILY, family_id=any_family_id)

    row = await ledger._get_or_create_pool_row(pool)
    before = row.total_savings

    await ledger.apply_movement(
        pool,
        Decimal("100"),
        LEDGER_IN,
        LEDGER_SOURCE_MANUAL,
    )
    await ledger.apply_movement(
        pool,
        Decimal("40"),
        LEDGER_OUT,
        LEDGER_SOURCE_MANUAL,
    )
    await db_session.flush()

    row = await ledger._get_or_create_pool_row(pool)
    assert row.total_savings == before + Decimal("60")

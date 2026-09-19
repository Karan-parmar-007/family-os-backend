from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.routes.expense.expense_schemas import ExpenseLogCreateRequest
from app.api.routes.expense.expense_service import ExpenseService
from app.api.routes.family_income.income_schemas import FamilyIncomeLogCreateRequest
from app.api.routes.family_income.income_service import IncomeService
from app.api.routes.family.model import Family, LogFundingSource
from app.api.routes.user.model import UserBase, UserFamilyLink
from app.api.schemas.funding import FundingSourceInput
from app.core.constants import LEDGER_IN, LEDGER_SOURCE_MANUAL, POOL_FAMILY, POOL_PERSONAL
from app.core.funding_sources import validate_family_personal_log_split, validate_log_funding_sources
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef


def test_validate_family_personal_log_split_ok():
    validate_family_personal_log_split(Decimal("100"), Decimal("60"), Decimal("40"))


def test_validate_family_personal_log_split_rejects_family_equals_total():
    with pytest.raises(ValueError, match="less than the total"):
        validate_family_personal_log_split(Decimal("100"), Decimal("100"), Decimal("0"))


def test_validate_family_personal_log_split_rejects_personal_equals_total():
    with pytest.raises(ValueError, match="less than the total"):
        validate_family_personal_log_split(Decimal("100"), Decimal("0"), Decimal("100"))


def test_validate_family_personal_log_split_rejects_missing_personal():
    with pytest.raises(ValueError, match="greater than zero"):
        validate_family_personal_log_split(Decimal("100"), Decimal("100"), None)


def test_validate_log_funding_sources_rejects_primary_family_only_total():
    family_id = uuid4()
    with pytest.raises(ValueError, match="greater than zero"):
        validate_log_funding_sources(
            Decimal("100"),
            [FundingSourceInput(pool_type=POOL_FAMILY, family_id=family_id, amount=Decimal("100"))],
            family_id,
        )


def test_validate_log_funding_sources_allows_other_family_only_total():
    primary_id = uuid4()
    other_id = uuid4()
    validate_log_funding_sources(
        Decimal("100"),
        [FundingSourceInput(pool_type=POOL_FAMILY, family_id=other_id, amount=Decimal("100"))],
        primary_id,
    )


def test_family_income_log_create_rejects_family_only_total():
    with pytest.raises(ValueError, match="greater than zero"):
        FamilyIncomeLogCreateRequest(
            income_name="Salary",
            total_amount=Decimal("100"),
            income_date=datetime.now(timezone.utc),
            family_amount=Decimal("100"),
        )


def test_family_expense_log_create_rejects_family_only_total():
    from app.api.routes.family_expense.expense_schemas import FamilyExpenseLogCreateRequest

    with pytest.raises(ValueError, match="greater than zero"):
        FamilyExpenseLogCreateRequest(
            expense_name="Groceries",
            total_amount=Decimal("100"),
            expense_date=datetime.now(timezone.utc),
            family_amount=Decimal("100"),
        )


@pytest.mark.integration
async def test_expense_log_supports_multi_source_funding(db_session):
    import uuid
    suffix = uuid.uuid4().hex[:8]
    user = UserBase(email=f"fund-user-{suffix}@example.com", name="Fund", password="x")
    family_a = Family(name="Family A", currency="USD")
    family_b = Family(name="Family B", currency="USD")
    db_session.add_all([user, family_a, family_b])
    await db_session.flush()

    db_session.add(UserFamilyLink(user_id=user.id, family_id=family_a.id, is_family_manager=True))
    db_session.add(UserFamilyLink(user_id=user.id, family_id=family_b.id, is_family_manager=False))
    await db_session.commit()

    ledger = SavingsLedgerService(db_session)
    await ledger.apply_movement(
        SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_a.id),
        Decimal("100"),
        LEDGER_IN,
        LEDGER_SOURCE_MANUAL,
    )
    await ledger.apply_movement(
        SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_b.id),
        Decimal("100"),
        LEDGER_IN,
        LEDGER_SOURCE_MANUAL,
    )
    await ledger.apply_movement(
        SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=user.id),
        Decimal("100"),
        LEDGER_IN,
        LEDGER_SOURCE_MANUAL,
    )
    await db_session.commit()

    service = ExpenseService(db_session)
    log, _ = await service.create_log(
        family_id=family_a.id,
        logged_by=user.id,
        request=ExpenseLogCreateRequest(
            expense_name="Phone",
            amount=Decimal("60"),
            expense_date=datetime.now(timezone.utc),
            is_personal=True,
            funding_sources=[
                FundingSourceInput(pool_type=POOL_FAMILY, family_id=family_a.id, amount=Decimal("30")),
                FundingSourceInput(pool_type=POOL_FAMILY, family_id=family_b.id, amount=Decimal("20")),
                FundingSourceInput(pool_type=POOL_PERSONAL, user_id=user.id, amount=Decimal("10")),
            ],
        ),
    )
    assert log.id is not None

    funding_rows = list(
        (await db_session.execute(select(LogFundingSource).where(LogFundingSource.entity_id == log.id)))
        .scalars()
        .all()
    )
    assert len(funding_rows) == 3

    row_a = await ledger._get_or_create_pool_row(SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_a.id))
    row_b = await ledger._get_or_create_pool_row(SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_b.id))
    row_g = await ledger._get_or_create_pool_row(SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=user.id))
    assert row_a.total_savings == Decimal("70")
    assert row_b.total_savings == Decimal("80")
    assert row_g.total_savings == Decimal("90")


@pytest.mark.integration
async def test_income_log_supports_multi_source_funding(db_session):
    import uuid
    suffix = uuid.uuid4().hex[:8]
    user = UserBase(email=f"income-fund-user-{suffix}@example.com", name="Income", password="x")
    family_a = Family(name="Income Family A", currency="USD")
    family_b = Family(name="Income Family B", currency="USD")
    db_session.add_all([user, family_a, family_b])
    await db_session.flush()

    db_session.add(UserFamilyLink(user_id=user.id, family_id=family_a.id, is_family_manager=True))
    db_session.add(UserFamilyLink(user_id=user.id, family_id=family_b.id, is_family_manager=False))
    await db_session.commit()

    service = IncomeService(db_session, garage_client=None)
    log, family_updated, personal_updated, _ = await service.create_family_income_log(
        family_id=family_a.id,
        logged_by_user_id=user.id,
        data=FamilyIncomeLogCreateRequest(
            income_name="Salary",
            total_amount=Decimal("100"),
            income_date=datetime.now(timezone.utc),
            earned_by_user_id=user.id,
            funding_sources=[
                FundingSourceInput(pool_type=POOL_FAMILY, family_id=family_a.id, amount=Decimal("50")),
                FundingSourceInput(pool_type=POOL_FAMILY, family_id=family_b.id, amount=Decimal("20")),
                FundingSourceInput(pool_type=POOL_PERSONAL, user_id=user.id, amount=Decimal("30")),
            ],
        ),
    )

    assert log.id is not None
    assert family_updated == Decimal("50")
    assert personal_updated == Decimal("30")

    ledger = SavingsLedgerService(db_session)
    row_a = await ledger._get_or_create_pool_row(SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_a.id))
    row_b = await ledger._get_or_create_pool_row(SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_b.id))
    row_g = await ledger._get_or_create_pool_row(SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=user.id))
    assert row_a.total_savings == Decimal("50")
    assert row_b.total_savings == Decimal("20")
    assert row_g.total_savings == Decimal("30")

"""Tests for debt validation, interest/EMI rules, and part-payment math."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.api.routes.debt.debt_validation import (
    normalize_emi_fields,
    normalize_interest_fields,
    validate_debt_type,
    validate_mask_fields,
)
from app.core.interest_math import (
    INTEREST_COMPOUND,
    INTEREST_FIXED_FEE,
    INTEREST_FLOATING,
    INTEREST_NONE,
    INTEREST_REDUCING_MONTHLY,
    recompute_after_part_payment,
)


def test_validate_debt_type_rejects_unknown():
    with pytest.raises(ValueError):
        validate_debt_type("NOT_A_REAL_TYPE")


def test_has_interest_false_clears_fields():
    cleaned = normalize_interest_fields(
        has_interest=False,
        interest_type=INTEREST_REDUCING_MONTHLY,
        interest_rate=12.0,
        compounding_frequency="MONTHLY",
        fixed_fee_amount=Decimal("10"),
    )
    assert cleaned["has_interest"] is False
    assert cleaned["interest_type"] == INTEREST_NONE
    assert cleaned["interest_rate"] is None
    assert cleaned["fixed_fee_amount"] is None


def test_has_interest_true_rejects_none():
    with pytest.raises(ValueError, match="NONE is not allowed"):
        normalize_interest_fields(
            has_interest=True,
            interest_type=INTEREST_NONE,
            interest_rate=None,
            compounding_frequency=None,
            fixed_fee_amount=None,
        )


def test_fixed_fee_requires_amount():
    with pytest.raises(ValueError, match="fixed_fee_amount"):
        normalize_interest_fields(
            has_interest=True,
            interest_type=INTEREST_FIXED_FEE,
            interest_rate=None,
            compounding_frequency=None,
            fixed_fee_amount=None,
        )


def test_compound_requires_frequency():
    with pytest.raises(ValueError, match="compounding_frequency"):
        normalize_interest_fields(
            has_interest=True,
            interest_type=INTEREST_COMPOUND,
            interest_rate=8.0,
            compounding_frequency=None,
            fixed_fee_amount=None,
        )


def test_floating_accepted_with_rate():
    cleaned = normalize_interest_fields(
        has_interest=True,
        interest_type=INTEREST_FLOATING,
        interest_rate=9.5,
        compounding_frequency=None,
        fixed_fee_amount=None,
    )
    assert cleaned["interest_type"] == INTEREST_FLOATING
    assert cleaned["interest_rate"] == 9.5


def test_emi_requires_next_date_and_amount_or_tenure():
    with pytest.raises(ValueError, match="emi_next_date"):
        normalize_emi_fields(
            has_emi=True,
            principal=Decimal("10000"),
            has_interest=False,
            interest_type=INTEREST_NONE,
            interest_rate=None,
            compounding_frequency=None,
            emi_amount=Decimal("500"),
            emi_every="MONTHLY",
            tenure_months=20,
            emi_next_date=None,
        )

    with pytest.raises(ValueError, match="emi_amount or tenure"):
        normalize_emi_fields(
            has_emi=True,
            principal=Decimal("10000"),
            has_interest=False,
            interest_type=INTEREST_NONE,
            interest_rate=None,
            compounding_frequency=None,
            emi_amount=None,
            emi_every="MONTHLY",
            tenure_months=None,
            emi_next_date=datetime.now(timezone.utc),
        )


def test_emi_computes_from_tenure():
    result = normalize_emi_fields(
        has_emi=True,
        principal=Decimal("12000"),
        has_interest=False,
        interest_type=INTEREST_NONE,
        interest_rate=None,
        compounding_frequency=None,
        emi_amount=None,
        emi_every="MONTHLY",
        tenure_months=12,
        emi_next_date=datetime.now(timezone.utc),
    )
    assert result["emi_amount"] == Decimal("1000.00")


def test_mask_requires_display_fields():
    with pytest.raises(ValueError, match="display total"):
        validate_mask_fields(
            is_masked=True,
            display_total=None,
            display_remaining=Decimal("1"),
            display_emi=Decimal("1"),
            display_rate=1.0,
            has_emi=True,
            has_interest=True,
        )


def test_recompute_reduce_emi_and_tenure():
    reduced_emi = recompute_after_part_payment(
        remaining=Decimal("80000"),
        current_emi=Decimal("9000"),
        annual_rate_pct=12.0,
        interest_type=INTEREST_REDUCING_MONTHLY,
        remaining_periods=12,
        mode="REDUCE_EMI",
    )
    assert reduced_emi["new_emi"] < Decimal("9000")
    assert reduced_emi["new_periods"] == 12

    reduced_tenure = recompute_after_part_payment(
        remaining=Decimal("80000"),
        current_emi=Decimal("9000"),
        annual_rate_pct=12.0,
        interest_type=INTEREST_REDUCING_MONTHLY,
        remaining_periods=12,
        mode="REDUCE_TENURE",
    )
    assert reduced_tenure["new_emi"] == Decimal("9000")
    assert reduced_tenure["new_periods"] < 12

from decimal import Decimal

import pytest

from app.core.interest_math import (
    COMPOUNDING_MONTHLY,
    COMPOUNDING_QUARTERLY,
    COMPOUNDING_YEARLY,
    INTEREST_COMPOUND,
    INTEREST_FIXED_FEE,
    INTEREST_FLAT,
    INTEREST_FLOATING,
    INTEREST_NONE,
    INTEREST_REDUCING_MONTHLY,
    INTEREST_REDUCING_YEARLY,
    INTEREST_SIMPLE,
    INTEREST_TYPES,
    compute_emi,
    compute_tenure,
    quote,
    recompute_after_part_payment,
    recompute_after_skip,
    split_emi,
)


# ---------------------------------------------------------------------------
# Existing tests (must continue passing)
# ---------------------------------------------------------------------------


def test_calculate_emi_none_interest():
    emi = compute_emi(
        principal=Decimal("12000"),
        annual_rate_pct=0,
        interest_type=INTEREST_NONE,
        tenure_months=12,
    )
    assert emi == Decimal("1000.00")


def test_calculate_emi_reducing_monthly():
    emi = compute_emi(
        principal=Decimal("100000"),
        annual_rate_pct=12.0,
        interest_type=INTEREST_REDUCING_MONTHLY,
        tenure_months=12,
    )
    assert emi > Decimal("8800")
    assert emi < Decimal("9000")


def test_recompute_after_skip_increases_emi():
    new_emi = recompute_after_skip(
        Decimal("100000"),
        12.0,
        INTEREST_REDUCING_MONTHLY,
        11,
    )
    assert new_emi > Decimal("9000")


# ---------------------------------------------------------------------------
# SIMPLE interest
# ---------------------------------------------------------------------------


def test_compute_emi_simple():
    """SIMPLE EMI = (P + P*r*years) / n — same formula as FLAT."""
    # P=120000, 10% annual, 12 months
    # total_interest = 120000 * 0.10 * 1 = 12000
    # EMI = (120000 + 12000) / 12 = 11000.00
    emi = compute_emi(
        principal=Decimal("120000"),
        annual_rate_pct=10.0,
        interest_type=INTEREST_SIMPLE,
        tenure_months=12,
    )
    assert emi == Decimal("11000.00")


def test_compute_tenure_simple():
    """compute_tenure for SIMPLE should invert compute_emi."""
    emi = compute_emi(
        principal=Decimal("120000"),
        annual_rate_pct=10.0,
        interest_type=INTEREST_SIMPLE,
        tenure_months=12,
    )
    n = compute_tenure(
        principal=Decimal("120000"),
        annual_rate_pct=10.0,
        emi_amount=emi,
        interest_type=INTEREST_SIMPLE,
    )
    assert n == 12


def test_compute_emi_simple_zero_rate():
    """SIMPLE with 0% rate should equal NONE."""
    emi = compute_emi(
        principal=Decimal("60000"),
        annual_rate_pct=0.0,
        interest_type=INTEREST_SIMPLE,
        tenure_months=12,
    )
    assert emi == Decimal("5000.00")


# ---------------------------------------------------------------------------
# COMPOUND interest
# ---------------------------------------------------------------------------


def test_compute_emi_compound_monthly_matches_reducing():
    """COMPOUND with MONTHLY frequency should produce same EMI as REDUCING_MONTHLY."""
    P = Decimal("100000")
    r = 12.0
    n = 12
    emi_reducing = compute_emi(P, r, n, INTEREST_REDUCING_MONTHLY)
    emi_compound = compute_emi(
        P, r, n, INTEREST_COMPOUND, compounding_frequency=COMPOUNDING_MONTHLY
    )
    assert emi_reducing == emi_compound


def test_compute_emi_compound_yearly_differs_from_monthly():
    """Yearly compounding produces a different (lower) EMI than monthly for same nominal rate."""
    P = Decimal("100000")
    r = 12.0
    n = 12
    emi_monthly = compute_emi(
        P, r, n, INTEREST_COMPOUND, compounding_frequency=COMPOUNDING_MONTHLY
    )
    emi_yearly = compute_emi(
        P, r, n, INTEREST_COMPOUND, compounding_frequency=COMPOUNDING_YEARLY
    )
    # Yearly compounding → lower effective monthly rate → lower EMI
    assert emi_yearly < emi_monthly
    # Both should be in a reasonable range for a 12% 12-month loan
    assert Decimal("8800") < emi_yearly < Decimal("8900")
    assert Decimal("8800") < emi_monthly < Decimal("9000")


def test_compute_tenure_compound():
    """compute_tenure for COMPOUND should round-trip with compute_emi."""
    P = Decimal("100000")
    r = 12.0
    n_expected = 24
    emi = compute_emi(
        P, r, n_expected, INTEREST_COMPOUND, compounding_frequency=COMPOUNDING_QUARTERLY
    )
    n_actual = compute_tenure(
        P, r, emi, INTEREST_COMPOUND, compounding_frequency=COMPOUNDING_QUARTERLY
    )
    assert n_actual == n_expected


def test_split_emi_compound_uses_effective_rate():
    """split_emi for COMPOUND should use monthly-equivalent rate for interest portion."""
    P = Decimal("100000")
    r_pct = 12.0
    emi = compute_emi(
        P, r_pct, 12, INTEREST_COMPOUND, compounding_frequency=COMPOUNDING_YEARLY
    )
    interest, principal = split_emi(
        emi, P, r_pct, INTEREST_COMPOUND, compounding_frequency=COMPOUNDING_YEARLY
    )
    assert interest > _ZERO()
    assert principal > _ZERO()
    assert interest + principal == emi


def _ZERO():
    return Decimal("0")


# ---------------------------------------------------------------------------
# quote()
# ---------------------------------------------------------------------------


def test_quote_reducing_monthly_derive_emi():
    """quote() should derive EMI when given tenure + rate."""
    q = quote(
        Decimal("100000"),
        INTEREST_REDUCING_MONTHLY,
        annual_rate_pct=12.0,
        tenure_months=12,
    )
    assert q["tenure_months"] == 12
    assert q["annual_rate_pct"] == 12.0
    assert q["interest_type"] == INTEREST_REDUCING_MONTHLY
    # EMI should match compute_emi directly
    expected_emi = compute_emi(Decimal("100000"), 12.0, 12, INTEREST_REDUCING_MONTHLY)
    assert q["emi"] == expected_emi
    assert q["total_payable"] == expected_emi * 12
    assert q["total_interest"] == q["total_payable"] - Decimal("100000")


def test_quote_reducing_monthly_derive_tenure():
    """quote() should derive tenure when given EMI + rate."""
    emi = compute_emi(Decimal("100000"), 12.0, 12, INTEREST_REDUCING_MONTHLY)
    q = quote(
        Decimal("100000"),
        INTEREST_REDUCING_MONTHLY,
        annual_rate_pct=12.0,
        emi_amount=emi,
    )
    assert q["tenure_months"] == 12
    assert q["emi"] == emi
    assert q["total_payable"] > Decimal("100000")
    assert q["total_interest"] > Decimal("0")


def test_quote_none_derive_emi():
    """quote() for NONE derives EMI from tenure, total_interest=0."""
    q = quote(Decimal("12000"), INTEREST_NONE, tenure_months=12)
    assert q["emi"] == Decimal("1000.00")
    assert q["tenure_months"] == 12
    assert q["total_interest"] == Decimal("0")
    assert q["total_payable"] == Decimal("12000")


def test_quote_none_derive_tenure():
    """quote() for NONE derives tenure from EMI."""
    q = quote(Decimal("12000"), INTEREST_NONE, emi_amount=Decimal("1000"))
    assert q["tenure_months"] == 12
    assert q["total_interest"] == Decimal("0")


def test_quote_fixed_fee():
    """quote() for FIXED_FEE: total_payable = P + fee, total_interest = fee."""
    q = quote(
        Decimal("10000"),
        INTEREST_FIXED_FEE,
        tenure_months=10,
        fixed_fee_amount=Decimal("500"),
    )
    assert q["emi"] == Decimal("1000.00")  # P/n = 10000/10
    assert q["tenure_months"] == 10
    assert q["total_interest"] == Decimal("500")
    assert q["total_payable"] == Decimal("10500")


def test_quote_compound_yearly():
    """quote() for COMPOUND yearly produces consistent EMI and total values."""
    q = quote(
        Decimal("100000"),
        INTEREST_COMPOUND,
        annual_rate_pct=12.0,
        compounding_frequency=COMPOUNDING_YEARLY,
        tenure_months=12,
    )
    assert q["compounding_frequency"] == COMPOUNDING_YEARLY
    expected_emi = compute_emi(
        Decimal("100000"), 12.0, 12, INTEREST_COMPOUND,
        compounding_frequency=COMPOUNDING_YEARLY,
    )
    assert q["emi"] == expected_emi
    assert q["total_payable"] == expected_emi * 12
    assert q["total_interest"] == q["total_payable"] - Decimal("100000")


def test_quote_missing_params_raises():
    """quote() should raise ValueError when insufficient params are provided."""
    with pytest.raises(ValueError):
        quote(Decimal("10000"), INTEREST_REDUCING_MONTHLY, annual_rate_pct=12.0)


# ---------------------------------------------------------------------------
# recompute_after_part_payment
# ---------------------------------------------------------------------------


def test_recompute_part_payment_reduce_emi():
    """REDUCE_EMI keeps tenure, recomputes lower EMI from new remaining."""
    # Original: 100000, 12%, 12 months
    original_emi = compute_emi(Decimal("100000"), 12.0, 12, INTEREST_REDUCING_MONTHLY)
    result = recompute_after_part_payment(
        remaining=Decimal("80000"),
        current_emi=original_emi,
        annual_rate_pct=12.0,
        interest_type=INTEREST_REDUCING_MONTHLY,
        remaining_periods=12,
        mode="REDUCE_EMI",
    )
    expected_new_emi = compute_emi(Decimal("80000"), 12.0, 12, INTEREST_REDUCING_MONTHLY)
    assert result["new_emi"] == expected_new_emi
    assert result["new_emi"] < original_emi
    assert result["new_periods"] == 12
    assert result["note"] == "EMI reduced"


def test_recompute_part_payment_reduce_tenure():
    """REDUCE_TENURE keeps EMI, recomputes fewer periods from new remaining."""
    original_emi = compute_emi(Decimal("100000"), 12.0, 12, INTEREST_REDUCING_MONTHLY)
    result = recompute_after_part_payment(
        remaining=Decimal("80000"),
        current_emi=original_emi,
        annual_rate_pct=12.0,
        interest_type=INTEREST_REDUCING_MONTHLY,
        remaining_periods=12,
        mode="REDUCE_TENURE",
    )
    assert result["new_emi"] == original_emi
    # Fewer months needed to pay off reduced principal
    assert result["new_periods"] < 12
    assert result["note"] == "Tenure reduced"


def test_recompute_part_payment_fully_paid():
    """Remaining = 0 returns zeroed-out dict."""
    result = recompute_after_part_payment(
        remaining=Decimal("0"),
        current_emi=Decimal("5000"),
        annual_rate_pct=12.0,
        interest_type=INTEREST_REDUCING_MONTHLY,
        remaining_periods=6,
        mode="REDUCE_EMI",
    )
    assert result["new_emi"] == Decimal("0")
    assert result["new_periods"] == 0


# ---------------------------------------------------------------------------
# recompute_after_skip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "interest_type,rate,freq",
    [
        (INTEREST_NONE, 0.0, COMPOUNDING_MONTHLY),
        (INTEREST_FLAT, 10.0, COMPOUNDING_MONTHLY),
        (INTEREST_REDUCING_MONTHLY, 12.0, COMPOUNDING_MONTHLY),
        (INTEREST_REDUCING_YEARLY, 12.0, COMPOUNDING_YEARLY),
        (INTEREST_SIMPLE, 10.0, COMPOUNDING_MONTHLY),
        (INTEREST_COMPOUND, 12.0, COMPOUNDING_QUARTERLY),
        (INTEREST_FIXED_FEE, 0.0, COMPOUNDING_MONTHLY),
        (INTEREST_FLOATING, 11.0, COMPOUNDING_MONTHLY),
    ],
)
def test_all_eight_interest_types_compute_emi_and_tenure(interest_type, rate, freq):
    """Every supported interest type can compute EMI and round-trip tenure."""
    assert interest_type in INTEREST_TYPES
    principal = Decimal("120000")
    tenure = 24
    emi = compute_emi(principal, rate, tenure, interest_type, freq)
    assert emi > Decimal("0")
    if interest_type not in (INTEREST_NONE, INTEREST_FIXED_FEE) and rate > 0:
        n = compute_tenure(principal, rate, emi, interest_type, freq)
        assert n >= 1
    # Part-payment paths must not crash
    reduced = recompute_after_part_payment(
        Decimal("90000"), emi, rate, interest_type, tenure, "REDUCE_EMI", freq
    )
    assert reduced["new_emi"] > Decimal("0") or reduced["new_periods"] == 0
    tenure_mode = recompute_after_part_payment(
        Decimal("90000"), emi, rate, interest_type, tenure, "REDUCE_TENURE", freq
    )
    assert tenure_mode["new_periods"] >= 1
    # Skip accrual either increases EMI or leaves principal-only EMI unchanged
    skipped = recompute_after_skip(
        Decimal("100000"), rate, interest_type, 20, freq
    )
    assert skipped > Decimal("0")


def test_flat_emi_equals_simple_style_total_over_tenure():
    emi = compute_emi(Decimal("100000"), 12.0, 12, INTEREST_FLAT)
    # Flat: total interest = P*r*years = 12000; EMI = 112000/12
    assert emi == Decimal("9333.33")


def test_reducing_yearly_emi_positive():
    emi = compute_emi(Decimal("200000"), 10.0, 24, INTEREST_REDUCING_YEARLY)
    assert emi > Decimal("8000")
    assert emi < Decimal("12000")


def test_floating_matches_reducing_monthly_math():
    a = compute_emi(Decimal("100000"), 12.0, 12, INTEREST_FLOATING)
    b = compute_emi(Decimal("100000"), 12.0, 12, INTEREST_REDUCING_MONTHLY)
    assert a == b


def test_recompute_after_skip_compound():
    """recompute_after_skip works for COMPOUND loans, accrues one period interest."""
    new_emi = recompute_after_skip(
        Decimal("100000"),
        12.0,
        INTEREST_COMPOUND,
        11,
        compounding_frequency=COMPOUNDING_YEARLY,
    )
    # Should be higher than the standard compound EMI (because interest was added)
    standard_emi = compute_emi(
        Decimal("100000"), 12.0, 11, INTEREST_COMPOUND,
        compounding_frequency=COMPOUNDING_YEARLY,
    )
    assert new_emi > standard_emi

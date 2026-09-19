"""Strict validation helpers for debt create/update."""
from __future__ import annotations

from decimal import Decimal

from app.core.interest_math import (
    COMPOUNDING_HALF_YEARLY,
    COMPOUNDING_MONTHLY,
    COMPOUNDING_QUARTERLY,
    COMPOUNDING_YEARLY,
    DEBT_TYPES,
    INTEREST_COMPOUND,
    INTEREST_FIXED_FEE,
    INTEREST_FLOATING,
    INTEREST_NONE,
    INTEREST_TYPES,
    compute_emi,
    compute_tenure,
)

_VALID_COMPOUNDING = {
    COMPOUNDING_MONTHLY,
    COMPOUNDING_QUARTERLY,
    COMPOUNDING_HALF_YEARLY,
    COMPOUNDING_YEARLY,
}

_RATE_REQUIRED = {
    t for t in INTEREST_TYPES if t not in (INTEREST_NONE, INTEREST_FIXED_FEE)
}


def validate_debt_type(debt_type: str) -> None:
    if debt_type not in DEBT_TYPES:
        raise ValueError(f"Invalid debt type: {debt_type}")


def normalize_interest_fields(
    *,
    has_interest: bool,
    interest_type: str | None,
    interest_rate: float | None,
    compounding_frequency: str | None,
    fixed_fee_amount: Decimal | None,
    interest_increase_every: str | None = None,
    interest_increase_percentage: float | None = None,
    next_interest_increase_date=None,
) -> dict:
    """Return cleaned interest fields. Clears all when has_interest is false."""
    if not has_interest:
        return {
            "has_interest": False,
            "interest_type": INTEREST_NONE,
            "interest_rate": None,
            "compounding_frequency": None,
            "fixed_fee_amount": None,
            "interest_increase_every": None,
            "interest_increase_percentage": None,
            "next_interest_increase_date": None,
        }

    if not interest_type or interest_type == INTEREST_NONE:
        raise ValueError(
            "When interest is enabled, choose a real interest type (NONE is not allowed)"
        )
    if interest_type not in INTEREST_TYPES:
        raise ValueError(f"Invalid interest type: {interest_type}")

    if interest_type == INTEREST_FIXED_FEE:
        if fixed_fee_amount is None or fixed_fee_amount < 0:
            raise ValueError("fixed_fee_amount is required for FIXED_FEE interest")
        return {
            "has_interest": True,
            "interest_type": interest_type,
            "interest_rate": None,
            "compounding_frequency": None,
            "fixed_fee_amount": fixed_fee_amount,
            "interest_increase_every": None,
            "interest_increase_percentage": None,
            "next_interest_increase_date": None,
        }

    if interest_type in _RATE_REQUIRED and (interest_rate is None or interest_rate < 0):
        raise ValueError(f"interest_rate is required for {interest_type}")

    if interest_type == INTEREST_COMPOUND:
        if not compounding_frequency or compounding_frequency not in _VALID_COMPOUNDING:
            raise ValueError(
                "compounding_frequency must be MONTHLY, QUARTERLY, HALF_YEARLY, or YEARLY"
            )
    else:
        compounding_frequency = None

    if interest_type == INTEREST_FLOATING:
        if interest_increase_every and interest_increase_percentage is None:
            raise ValueError(
                "interest_increase_percentage is required when a floating schedule is set"
            )
    else:
        interest_increase_every = None
        interest_increase_percentage = None
        next_interest_increase_date = None

    return {
        "has_interest": True,
        "interest_type": interest_type,
        "interest_rate": interest_rate,
        "compounding_frequency": compounding_frequency,
        "fixed_fee_amount": None,
        "interest_increase_every": interest_increase_every,
        "interest_increase_percentage": interest_increase_percentage,
        "next_interest_increase_date": next_interest_increase_date,
    }


def validate_emi_calculation(
    *,
    principal: Decimal,
    annual_rate_pct: float,
    tenure_months: int,
    emi_amount: Decimal,
    interest_type: str,
    compounding_frequency: str = COMPOUNDING_MONTHLY,
    tolerance: Decimal = Decimal("1.00"),
) -> None:
    """Verify that submitted EMI matches the expected EMI for the given params.

    Raises ValueError if the difference exceeds `tolerance` (default ₹1).
    Also validates that the submitted tenure matches the derived tenure
    from the EMI amount (±1 month).
    """
    expected_emi = compute_emi(
        principal, annual_rate_pct, tenure_months, interest_type, compounding_frequency,
    )
    diff = abs(emi_amount - expected_emi)
    if diff > tolerance:
        raise ValueError(
            f"EMI mismatch: submitted {emi_amount}, expected ~{expected_emi} "
            f"for principal={principal}, rate={annual_rate_pct}%, "
            f"tenure={tenure_months} months, type={interest_type}. "
            f"Difference {diff} exceeds tolerance {tolerance}."
        )

    # Cross-check tenure
    try:
        derived_tenure = compute_tenure(
            principal, annual_rate_pct, emi_amount, interest_type, compounding_frequency,
        )
        if abs(derived_tenure - tenure_months) > 1:
            raise ValueError(
                f"Tenure mismatch: submitted {tenure_months} months but "
                f"derived {derived_tenure} months from the given EMI."
            )
    except ValueError as e:
        # If compute_tenure itself raises (e.g. EMI too small), propagate
        if "mismatch" in str(e):
            raise
        # Otherwise the EMI already passed the forward check, so this
        # is a marginal edge case — allow it.
        pass


def normalize_emi_fields(
    *,
    has_emi: bool,
    principal: Decimal,
    has_interest: bool,
    interest_type: str | None,
    interest_rate: float | None,
    compounding_frequency: str | None,
    emi_amount: Decimal | None,
    emi_every: str | None,
    emi_interval_days: int | None = None,
    emi_interval_months: int | None = None,
    emi_interval_years: int | None = None,
    tenure_months: int | None,
    emi_next_date,
    requires_confirmation: bool = True,
) -> dict:
    """Normalise EMI fields. Supports preset (emi_every) and custom intervals."""
    has_custom_interval = any([emi_interval_days, emi_interval_months, emi_interval_years])

    if not has_emi:
        return {
            "has_emi": False,
            "emi_amount": None,
            "emi_every": None,
            "emi_interval_days": None,
            "emi_interval_months": None,
            "emi_interval_years": None,
            "tenure_months": tenure_months,
            "emi_next_date": None,
            "requires_confirmation": requires_confirmation,
        }

    if emi_next_date is None:
        raise ValueError("emi_next_date is required when EMI is enabled")
    if not has_custom_interval and not emi_every:
        raise ValueError("emi_every or a custom interval is required when EMI is enabled")
    if emi_amount is None and (tenure_months is None or tenure_months <= 0):
        raise ValueError("Provide emi_amount or tenure_months when EMI is enabled")

    itype = interest_type or INTEREST_NONE
    if not has_interest:
        itype = INTEREST_NONE

    resolved_emi = emi_amount
    resolved_tenure = tenure_months

    if resolved_emi is None and resolved_tenure and resolved_tenure > 0:
        # Auto-calculate EMI from tenure
        resolved_emi = compute_emi(
            principal,
            interest_rate or 0.0,
            resolved_tenure,
            itype,
            compounding_frequency or COMPOUNDING_MONTHLY,
        )
    elif resolved_emi and resolved_emi > 0 and (resolved_tenure is None or resolved_tenure <= 0):
        # Auto-calculate tenure from EMI
        try:
            resolved_tenure = compute_tenure(
                principal,
                interest_rate or 0.0,
                resolved_emi,
                itype,
                compounding_frequency or COMPOUNDING_MONTHLY,
            )
        except ValueError:
            # If tenure can't be derived (e.g. EMI too small), just leave it None
            pass
    elif resolved_emi and resolved_emi > 0 and resolved_tenure and resolved_tenure > 0:
        # Both provided — cross-validate
        validate_emi_calculation(
            principal=principal,
            annual_rate_pct=interest_rate or 0.0,
            tenure_months=resolved_tenure,
            emi_amount=resolved_emi,
            interest_type=itype,
            compounding_frequency=compounding_frequency or COMPOUNDING_MONTHLY,
        )

    if resolved_emi is None or resolved_emi <= 0:
        raise ValueError("emi_amount must be positive")

    # When a custom interval is set, clear emi_every (and vice versa)
    resolved_every = None if has_custom_interval else emi_every
    resolved_interval_days = emi_interval_days if has_custom_interval else None
    resolved_interval_months = emi_interval_months if has_custom_interval else None
    resolved_interval_years = emi_interval_years if has_custom_interval else None

    return {
        "has_emi": True,
        "emi_amount": resolved_emi,
        "emi_every": resolved_every,
        "emi_interval_days": resolved_interval_days,
        "emi_interval_months": resolved_interval_months,
        "emi_interval_years": resolved_interval_years,
        "tenure_months": resolved_tenure,
        "emi_next_date": emi_next_date,
        "requires_confirmation": requires_confirmation,
    }


def validate_mask_fields(
    *,
    is_masked: bool,
    display_total: Decimal | None,
    display_remaining: Decimal | None,
    display_emi: Decimal | None,
    display_rate: float | None,
    has_emi: bool,
    has_interest: bool,
) -> None:
    if not is_masked:
        return
    if display_total is None or display_total < 0:
        raise ValueError("Masked family view requires display total amount")
    if display_remaining is None or display_remaining < 0:
        raise ValueError("Masked family view requires display remaining amount")
    if has_emi and display_emi is None:
        raise ValueError("Masked family view requires display EMI when EMI is enabled")
    if has_interest and display_rate is None:
        raise ValueError("Masked family view requires display interest rate when interest is enabled")

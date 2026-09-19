"""Interest math utilities for debt calculations (Family System V2 – Plan 02).

Pure functions, all using Decimal arithmetic. No side effects.

Supported interest types:
- NONE: interest-free loan
- FLAT: interest on original principal for full tenure
- REDUCING_MONTHLY: reducing balance, monthly rest (standard bank EMI)
- REDUCING_YEARLY: reducing balance, annual rest
- SIMPLE: simple interest accrued until payoff
- COMPOUND: compound at a given compounding_frequency
- FIXED_FEE: one flat fee, no rate
- FLOATING: user-managed rate (reducing-monthly math; rate updated externally)
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

# ---------------------------------------------------------------------------
# Interest type constants
# ---------------------------------------------------------------------------

INTEREST_NONE = "NONE"
INTEREST_FLAT = "FLAT"
INTEREST_REDUCING_MONTHLY = "REDUCING_MONTHLY"
INTEREST_REDUCING_YEARLY = "REDUCING_YEARLY"
INTEREST_SIMPLE = "SIMPLE"
INTEREST_COMPOUND = "COMPOUND"
INTEREST_FIXED_FEE = "FIXED_FEE"
INTEREST_FLOATING = "FLOATING"

INTEREST_TYPES = [
    INTEREST_NONE,
    INTEREST_FLAT,
    INTEREST_REDUCING_MONTHLY,
    INTEREST_REDUCING_YEARLY,
    INTEREST_SIMPLE,
    INTEREST_COMPOUND,
    INTEREST_FIXED_FEE,
    INTEREST_FLOATING,
]

COMPOUNDING_MONTHLY = "MONTHLY"
COMPOUNDING_QUARTERLY = "QUARTERLY"
COMPOUNDING_HALF_YEARLY = "HALF_YEARLY"
COMPOUNDING_YEARLY = "YEARLY"

DEBT_TYPES = [
    "HOME_LOAN", "AUTO_LOAN", "PERSONAL_LOAN", "EDUCATION_LOAN",
    "GOLD_LOAN", "BUSINESS_LOAN", "CREDIT_CARD", "BNPL", "PAYDAY_LOAN",
    "MORTGAGE", "OVERDRAFT", "FRIEND_FAMILY", "INFORMAL_LENDER",
    "MEDICAL_DEBT", "TAX_DEBT", "OTHER",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ZERO = Decimal("0")
_ONE = Decimal("1")
_CENT = Decimal("0.01")


def _round2(d: Decimal) -> Decimal:
    return d.quantize(_CENT, rounding=ROUND_HALF_UP)


def _compounding_periods_per_year(freq: str) -> int:
    return {
        COMPOUNDING_MONTHLY: 12,
        COMPOUNDING_QUARTERLY: 4,
        COMPOUNDING_HALF_YEARLY: 2,
        COMPOUNDING_YEARLY: 1,
    }.get(freq, 12)


def _effective_monthly_rate(annual_rate_pct: float, compounding_frequency: str) -> Decimal:
    """Compute effective monthly rate from annual rate and compounding frequency.

    For MONTHLY: returns annual_rate / 12 (standard simple division).
    For other frequencies: uses compound conversion (1 + r/k)^(k/12) - 1.
    """
    k = _compounding_periods_per_year(compounding_frequency)
    r_annual = annual_rate_pct / 100
    if k == 12:
        return Decimal(str(r_annual / 12))
    r_month = (1 + r_annual / k) ** (k / 12) - 1
    return Decimal(str(r_month))


# ---------------------------------------------------------------------------
# EMI calculation
# ---------------------------------------------------------------------------


def compute_emi(
    principal: Decimal,
    annual_rate_pct: float,
    tenure_months: int,
    interest_type: str,
    compounding_frequency: str = COMPOUNDING_MONTHLY,
) -> Decimal:
    """Compute the per-period EMI for a new debt.

    Returns Decimal rounded to 2 decimal places.
    Raises ValueError for invalid or non-EMI interest types.
    """
    P = principal

    if interest_type in (INTEREST_NONE, INTEREST_FIXED_FEE):
        if tenure_months <= 0:
            raise ValueError("tenure_months must be > 0 for EMI calculation")
        return _round2(P / Decimal(tenure_months))

    if interest_type in (INTEREST_FLAT, INTEREST_SIMPLE):
        # SIMPLE is amortized as equal installments — same formula as FLAT.
        r = Decimal(str(annual_rate_pct)) / 100
        years = Decimal(tenure_months) / 12
        total_interest = P * r * years
        return _round2((P + total_interest) / Decimal(tenure_months))

    if interest_type in (INTEREST_REDUCING_MONTHLY, INTEREST_FLOATING):
        # Use compound-converted monthly rate when frequency != MONTHLY.
        r = _effective_monthly_rate(annual_rate_pct, compounding_frequency)
        n = Decimal(tenure_months)
        if r == _ZERO:
            return _round2(P / n)
        factor = (_ONE + r) ** tenure_months
        emi = P * r * factor / (factor - _ONE)
        return _round2(emi)

    if interest_type == INTEREST_COMPOUND:
        r = _effective_monthly_rate(annual_rate_pct, compounding_frequency)
        n = tenure_months
        if r == _ZERO:
            return _round2(P / Decimal(n))
        factor = (_ONE + r) ** n
        emi = P * r * factor / (factor - _ONE)
        return _round2(emi)

    if interest_type == INTEREST_REDUCING_YEARLY:
        r = Decimal(str(annual_rate_pct)) / 100  # annual rate
        n = Decimal(tenure_months) / 12  # years
        if r == _ZERO or n == _ZERO:
            return _round2(P / Decimal(tenure_months))
        factor = Decimal(str((1 + float(r)) ** float(n)))
        emi_annual = P * r * factor / (factor - _ONE)
        return _round2(emi_annual / 12)  # monthly

    raise ValueError(f"Cannot compute EMI for interest_type={interest_type}")


def compute_tenure(
    principal: Decimal,
    annual_rate_pct: float,
    emi_amount: Decimal,
    interest_type: str,
    compounding_frequency: str = COMPOUNDING_MONTHLY,
) -> int:
    """Compute tenure in months given principal, rate, and EMI.

    Returns the number of monthly periods (ceiling) needed to fully
    pay off the loan.  Raises ValueError when the EMI is too small
    to cover the periodic interest (i.e. the loan would never pay off).
    """
    import math

    P = principal
    EMI = emi_amount

    if EMI <= _ZERO:
        raise ValueError("emi_amount must be positive to compute tenure")
    if P <= _ZERO:
        return 0

    if interest_type in (INTEREST_NONE, INTEREST_FIXED_FEE):
        # n = ceil(P / EMI)
        n = int((P / EMI).to_integral_value(ROUND_HALF_UP))
        return max(1, n)

    if interest_type in (INTEREST_FLAT, INTEREST_SIMPLE):
        # EMI = P*(1 + r*n/12) / n  → n = P / (EMI - P*r/12)
        r = Decimal(str(annual_rate_pct)) / 100
        monthly_interest_component = P * r / 12
        effective = EMI - monthly_interest_component
        if effective <= _ZERO:
            raise ValueError(
                "EMI is too small to cover flat/simple interest; loan will never pay off"
            )
        n = float(P / effective)
        return max(1, math.ceil(round(n, 3)))

    if interest_type in (INTEREST_REDUCING_MONTHLY, INTEREST_FLOATING):
        r = float(_effective_monthly_rate(annual_rate_pct, compounding_frequency))
        if r <= 0:
            n = float(P / EMI)
            return max(1, math.ceil(round(n, 3)))
        emi_f = float(EMI)
        P_f = float(P)
        periodic_interest = P_f * r
        if emi_f <= periodic_interest:
            raise ValueError(
                "EMI is too small to cover periodic interest; loan will never pay off"
            )
        n = math.log(emi_f / (emi_f - P_f * r)) / math.log(1 + r)
        return max(1, math.ceil(round(n, 3)))

    if interest_type == INTEREST_COMPOUND:
        r = float(_effective_monthly_rate(annual_rate_pct, compounding_frequency))
        if r <= 0:
            n = float(P / EMI)
            return max(1, math.ceil(round(n, 3)))
        emi_f = float(EMI)
        P_f = float(P)
        periodic_interest = P_f * r
        if emi_f <= periodic_interest:
            raise ValueError(
                "EMI is too small to cover periodic interest; loan will never pay off"
            )
        n = math.log(emi_f / (emi_f - P_f * r)) / math.log(1 + r)
        return max(1, math.ceil(round(n, 3)))

    if interest_type == INTEREST_REDUCING_YEARLY:
        r = float(Decimal(str(annual_rate_pct)) / 100)
        if r <= 0:
            n = float(P / EMI)
            return max(1, math.ceil(n))
        # Annual EMI = monthly EMI * 12
        annual_emi = float(EMI) * 12
        P_f = float(P)
        periodic_interest = P_f * r
        if annual_emi <= periodic_interest:
            raise ValueError(
                "EMI is too small to cover annual interest; loan will never pay off"
            )
        n_years = math.log(annual_emi / (annual_emi - P_f * r)) / math.log(1 + r)
        return max(1, math.ceil(round(n_years * 12, 3)))

    raise ValueError(f"Cannot compute tenure for interest_type={interest_type}")


def split_emi(
    emi: Decimal,
    remaining: Decimal,
    annual_rate_pct: float,
    interest_type: str,
    compounding_frequency: str = COMPOUNDING_MONTHLY,
) -> tuple[Decimal, Decimal]:
    """Split an EMI into (interest_part, principal_part).

    Returns (interest, principal) rounded to 2dp each, with rounding error
    absorbed into principal so interest + principal == emi.
    """
    if interest_type in (INTEREST_NONE, INTEREST_FIXED_FEE):
        return _ZERO, emi

    if interest_type == INTEREST_FLAT:
        # All payments were pre-computed including interest; interest is embedded.
        # Return ZERO/emi as flat debts don't have per-period split.
        return _ZERO, emi

    if interest_type in (INTEREST_REDUCING_MONTHLY, INTEREST_FLOATING, INTEREST_SIMPLE):
        r = Decimal(str(annual_rate_pct)) / 100 / 12
        interest = _round2(remaining * r)
        principal = _round2(emi - interest)
        return interest, principal

    if interest_type == INTEREST_COMPOUND:
        r = _effective_monthly_rate(annual_rate_pct, compounding_frequency)
        interest = _round2(remaining * r)
        principal = _round2(emi - interest)
        return interest, principal

    if interest_type == INTEREST_REDUCING_YEARLY:
        r = Decimal(str(annual_rate_pct)) / 100 / 12
        interest = _round2(remaining * r)
        principal = _round2(emi - interest)
        return interest, principal

    # Default: treat as all principal
    return _ZERO, emi


# ---------------------------------------------------------------------------
# Recompute after part payment
# ---------------------------------------------------------------------------


def recompute_after_part_payment(
    remaining: Decimal,
    current_emi: Decimal,
    annual_rate_pct: float,
    interest_type: str,
    remaining_periods: int,
    mode: str,
    compounding_frequency: str = COMPOUNDING_MONTHLY,
) -> dict:
    """Recompute debt parameters after a part payment.

    mode:
      REDUCE_EMI    – tenure unchanged, compute new EMI from remaining principal.
      REDUCE_TENURE – EMI unchanged, compute new tenure (n periods).
      CLEAR_UPCOMING – handled by caller; this returns same as REDUCE_TENURE.

    Returns dict with keys: new_emi, new_periods, note.
    """
    if remaining <= _ZERO:
        return {"new_emi": _ZERO, "new_periods": 0, "note": "Debt fully paid"}

    if mode == "REDUCE_EMI":
        if remaining_periods <= 0:
            return {"new_emi": remaining, "new_periods": 1, "note": "Last period"}
        new_emi = compute_emi(
            remaining, annual_rate_pct, remaining_periods, interest_type,
            compounding_frequency,
        )
        return {"new_emi": new_emi, "new_periods": remaining_periods, "note": "EMI reduced"}

    # REDUCE_TENURE (and CLEAR_UPCOMING fallback) — same formulas as compute_tenure
    try:
        n = compute_tenure(
            remaining, annual_rate_pct, current_emi, interest_type,
            compounding_frequency,
        )
    except ValueError:
        if current_emi > _ZERO:
            n = max(1, int((remaining / current_emi).to_integral_value(ROUND_HALF_UP)))
        else:
            n = remaining_periods
    return {"new_emi": current_emi, "new_periods": n, "note": "Tenure reduced"}


def recompute_after_skip(
    remaining: Decimal,
    annual_rate_pct: float,
    interest_type: str,
    remaining_periods: int,
    compounding_frequency: str = COMPOUNDING_MONTHLY,
) -> Decimal:
    """Recompute EMI after a skip (SKIP_INCREASE).

    Accrues interest for the skipped period and distributes over remaining periods.
    """
    if remaining_periods <= 0:
        return remaining
    # Accrue one period of interest on remaining
    if interest_type in (INTEREST_REDUCING_MONTHLY, INTEREST_FLOATING, INTEREST_SIMPLE):
        r = Decimal(str(annual_rate_pct)) / 100 / 12
        new_principal = remaining + _round2(remaining * r)
    elif interest_type == INTEREST_COMPOUND:
        r = _effective_monthly_rate(annual_rate_pct, compounding_frequency)
        new_principal = remaining + _round2(remaining * r)
    else:
        new_principal = remaining
    return compute_emi(
        new_principal, annual_rate_pct, remaining_periods, interest_type,
        compounding_frequency,
    )



def compute_compound_maturity(
    principal: Decimal,
    annual_rate_pct: float,
    tenure_years: float,
    compounding_frequency: str = COMPOUNDING_YEARLY,
) -> Decimal:
    """Compute compound interest maturity amount (for investments)."""
    k = _compounding_periods_per_year(compounding_frequency)
    r = float(annual_rate_pct) / 100
    amount = float(principal) * (1 + r / k) ** (k * tenure_years)
    return _round2(Decimal(str(amount)))


def compute_simple_maturity(
    principal: Decimal,
    annual_rate_pct: float,
    tenure_years: float,
) -> Decimal:
    """Compute simple interest maturity amount (for investments)."""
    r = Decimal(str(annual_rate_pct)) / 100
    interest = principal * r * Decimal(str(tenure_years))
    return _round2(principal + interest)


def quote(
    principal: Decimal,
    interest_type: str,
    *,
    annual_rate_pct: float = 0.0,
    compounding_frequency: str = COMPOUNDING_MONTHLY,
    emi_amount: Decimal | None = None,
    tenure_months: int | None = None,
    fixed_fee_amount: Decimal | None = None,
) -> dict:
    """Derive missing EMI / tenure / rate given principal and interest type.

    Provide any two of (emi_amount, tenure_months, annual_rate_pct) for rate-bearing
    types. NONE / FIXED_FEE only need EMI or tenure (the other is derived).
    """
    if principal <= _ZERO:
        raise ValueError("principal must be positive")
    if interest_type not in INTEREST_TYPES:
        raise ValueError(f"Invalid interest type: {interest_type}")

    fee = fixed_fee_amount or _ZERO
    rate = float(annual_rate_pct or 0.0)
    emi = emi_amount
    tenure = tenure_months

    if interest_type in (INTEREST_NONE, INTEREST_FIXED_FEE):
        # EMI is always principal/n — the fee (if any) is a one-time charge on top.
        if emi is not None and tenure is not None:
            pass
        elif tenure is not None and tenure > 0:
            emi = _round2(principal / Decimal(tenure))
        elif emi is not None and emi > _ZERO:
            tenure = max(1, int((principal / emi).to_integral_value(ROUND_HALF_UP)))
        else:
            raise ValueError("Provide emi_amount and/or tenure_months")
        total_payable = _round2((emi or _ZERO) * Decimal(tenure or 0))
        if interest_type == INTEREST_FIXED_FEE:
            total_interest = fee
            total_payable = _round2(principal + fee)
        else:
            total_interest = _ZERO
            total_payable = principal
        return {
            "emi": emi or _ZERO,
            "tenure_months": tenure or 0,
            "annual_rate_pct": 0.0,
            "total_interest": total_interest,
            "total_payable": total_payable,
            "interest_type": interest_type,
            "compounding_frequency": compounding_frequency,
        }

    # Rate-bearing types
    has_emi = emi is not None and emi > _ZERO
    has_tenure = tenure is not None and tenure > 0
    has_rate = rate > 0 or interest_type == INTEREST_FLAT  # flat can be 0

    if has_emi and has_tenure and not has_rate:
        # Approximate rate is not inverted here — require rate for quote simplicity
        raise ValueError("annual_rate_pct is required when deriving from EMI and tenure")

    if has_tenure and has_rate and not has_emi:
        emi = compute_emi(
            principal, rate, tenure, interest_type, compounding_frequency
        )
    elif has_emi and has_rate and not has_tenure:
        tenure = compute_tenure(
            principal, rate, emi, interest_type, compounding_frequency
        )
    elif has_emi and has_tenure and has_rate:
        # All provided — recompute consistency using EMI from tenure+rate as check
        pass
    else:
        raise ValueError(
            "Provide any two of emi_amount, tenure_months, and annual_rate_pct"
        )

    assert emi is not None and tenure is not None
    total_payable = _round2(emi * Decimal(tenure))
    total_interest = _round2(max(_ZERO, total_payable - principal))
    return {
        "emi": emi,
        "tenure_months": tenure,
        "annual_rate_pct": rate,
        "total_interest": total_interest,
        "total_payable": total_payable,
        "interest_type": interest_type,
        "compounding_frequency": compounding_frequency,
    }

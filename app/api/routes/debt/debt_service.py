"""Debt service — canonical Debt CRUD, EMI, and part payment."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import uuid6
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.debt.debt_presentation import DebtRow, build_debt_row
from app.api.routes.debt.debt_schemas import DebtCreateRequest, DebtUpdateRequest
from app.api.routes.debt.debt_validation import (
    normalize_emi_fields,
    normalize_interest_fields,
    validate_debt_type,
    validate_mask_fields,
)
from app.api.routes.debt.model import (
    Debt,
    DebtPaymentAllocation,
    DebtPaymentEvent,
    DebtScopeView,
)
from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.api.routes.user.model import UserFamilyLink
from app.api.schemas.pagination import PaginationParams
from app.core.constants import (
    ACCESS_SELECTED,
    JOB_STATUS_AWAITING_CONFIRMATION,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_SCHEDULED,
    LEDGER_OUT,
    LEDGER_SOURCE_DEBT_EMI,
    LEDGER_SOURCE_DEBT_PART_PAYMENT,
    NOTIF_STATUS_DISMISSED,
    SOURCE_DEBT,
)
from app.core.date_advance import advance_next_date
from app.core.default_bucket_service import DefaultBucketEntry, DefaultBucketService
from app.core.funding_service import FundingService, SplitLine
from app.core.interest_math import INTEREST_NONE, compute_emi, recompute_after_part_payment, split_emi
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef
from app.core.scope import ScopeContext, can_view_scoped_entity
from app.core.transfer_pools import scope_to_pool

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")

PartPaymentMode = Literal[
    "REDUCE_EMI",
    "REDUCE_TENURE",
    "CLEAR_UPCOMING",
    "ADVANCE_INSTALLMENTS",
    "REDUCE_BOTH",
    "FORECLOSURE",
]


def _round2(d: Decimal) -> Decimal:
    from decimal import ROUND_HALF_UP

    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _scale_split_lines_to_amount(
    lines: list[SplitLine], amount: Decimal
) -> list[SplitLine]:
    """Scale pool shares so they sum to `amount` (keeps relative weights)."""
    if amount <= _ZERO:
        return []
    total = sum((ln.amount for ln in lines), _ZERO)
    if total <= _ZERO:
        raise ValueError("Cannot fund part payment: split plan has no positive shares")
    scaled: list[SplitLine] = []
    allocated = _ZERO
    positive = [ln for ln in lines if ln.amount > _ZERO]
    for i, ln in enumerate(positive):
        if i == len(positive) - 1:
            share = _round2(amount - allocated)
        else:
            share = _round2(amount * (ln.amount / total))
            allocated += share
        if share > _ZERO:
            scaled.append(
                SplitLine(
                    pool_type=ln.pool_type,
                    amount=share,
                    family_id=ln.family_id,
                    user_id=ln.user_id,
                )
            )
    if not scaled:
        raise ValueError("Cannot fund part payment: scaled split is empty")
    # Final penny fix
    drift = _round2(amount - sum((ln.amount for ln in scaled), _ZERO))
    if abs(drift) >= Decimal("0.01"):
        last = scaled[-1]
        scaled[-1] = SplitLine(
            pool_type=last.pool_type,
            amount=_round2(last.amount + drift),
            family_id=last.family_id,
            user_id=last.user_id,
        )
    return scaled


def _split_line_to_dict(sl) -> dict[str, Any]:
    return {
        "poolType": sl.pool_type,
        "familyId": str(sl.family_id) if sl.family_id else None,
        "userId": str(sl.user_id) if sl.user_id else None,
        "amount": sl.amount,
        "expectedTotal": sl.expected_total,
        "obligationRemaining": sl.obligation_remaining,
    }


async def _load_debt_split_line_dicts(
    session: AsyncSession, debt_id: UUID, source_type: str | None = None
) -> list[dict[str, Any]]:
    fs = FundingService(session)
    plan = await fs.load_split_plan(SOURCE_DEBT, debt_id)
    if not plan:
        return []
    return [_split_line_to_dict(sl) for sl in plan]


def _request_split_line_dict(sl, *, default_personal_user_id: UUID | None = None) -> dict[str, Any]:
    ln: dict[str, Any] = {
        "pool_type": sl.poolType,
        "family_id": sl.familyId,
        "amount": sl.amount,
    }
    user_id_ln = getattr(sl, "userId", None) or getattr(sl, "user_id", None)
    if user_id_ln is None and sl.poolType == "PERSONAL":
        user_id_ln = default_personal_user_id
    if user_id_ln is not None:
        ln["user_id"] = user_id_ln
    expected = getattr(sl, "expectedTotal", None)
    obligation = getattr(sl, "obligationRemaining", None)
    if expected is not None:
        ln["expected_total"] = expected
    if obligation is not None:
        ln["obligation_remaining"] = obligation
    elif expected is not None:
        ln["obligation_remaining"] = expected
    return ln


def debt_owner_id(debt: Debt) -> UUID | None:
    return debt.owner_user_id


def require_debt_owner(actor_id: UUID, debt) -> None:
    """Only the debt owner may apply part payments or edit it."""
    owner = debt.owner_user_id
    if owner is None or owner != actor_id:
        raise PermissionError(
            "Only the person who added this debt may apply part payments or edit it. "
            "Other payers can contribute to the part-payment balance instead."
        )


def _emi_advance_kwargs(debt) -> dict:
    """Return advance_next_date kwargs for a debt's EMI schedule."""
    days = getattr(debt, "emi_interval_days", None)
    months = getattr(debt, "emi_interval_months", None)
    years = getattr(debt, "emi_interval_years", None)
    if days or months or years:
        return {
            "interval_days": days,
            "interval_months": months,
            "interval_years": years,
        }
    return {"every": debt.emi_every or "MONTHLY"}


def _source_type(debt: Debt) -> str:
    return SOURCE_DEBT


def _default_pool_ref(debt) -> SavingsPoolRef:
    """Return default pool for a debt. Uses primary_family_id → family pool; else personal of owner."""
    if debt.primary_family_id:
        return scope_to_pool("FAMILY", family_id=debt.primary_family_id)
    return scope_to_pool("PERSONAL", user_id=debt.owner_user_id)


def _real_remaining(debt: Debt) -> Decimal:
    return debt.remaining_amount or _ZERO


def _normalize_part_mode(mode: str) -> str:
    if mode == "ADVANCE_INSTALLMENTS":
        return "CLEAR_UPCOMING"
    return mode


# ---------------------------------------------------------------------------
# Canonical resolver
# ---------------------------------------------------------------------------


async def resolve_debt(
    session: AsyncSession, debt_id: UUID
) -> Debt | None:
    """Load canonical Debt by id — primary resolver for all new paths."""
    return (
        await session.execute(select(Debt).where(Debt.id == debt_id))
    ).scalar_one_or_none()

async def _sync_primary_family_view_display(
    session: AsyncSession,
    canonical: Debt,
    *,
    old_real_remaining: Decimal,
    new_real_remaining: Decimal,
) -> None:
    """Proportionally update masked primary FAMILY view display remaining."""
    view = (
        await session.execute(
            select(DebtScopeView).where(
                DebtScopeView.debt_id == canonical.id,
                DebtScopeView.scope_kind == "FAMILY",
                DebtScopeView.is_primary.is_(True),
            )
        )
    ).scalar_one_or_none()
    if view is None or not view.is_masked:
        return

    if old_real_remaining > _ZERO and view.display_remaining_amount is not None:
        ratio = new_real_remaining / old_real_remaining
        view.display_remaining_amount = _round2(view.display_remaining_amount * ratio)
    else:
        view.display_remaining_amount = canonical.remaining_amount

    if view.display_emi_amount is not None and canonical.emi_amount is not None:
        view.display_emi_amount = canonical.emi_amount
    await session.flush()


async def finalize_payment_event(
    session: AsyncSession,
    debt_id: UUID,
    *,
    event_type: str,
    period_key: str | None = None,
    scheduled_amount: Decimal | None = None,
    actual_amount: Decimal,
    principal: Decimal = _ZERO,
    interest: Decimal = _ZERO,
    fees: Decimal = _ZERO,
    paid_at: datetime | None = None,
    paid_externally: bool = False,
    job_id: UUID | None = None,
    allocations: list[dict] | None = None,
    part_payment_mode: str | None = None,
    underpayment_policy: str | None = None,
    overpayment_policy: str | None = None,
    note: str | None = None,
    created_by: UUID | None = None,
) -> DebtPaymentEvent | None:
    """Create a FINALIZED DebtPaymentEvent (+ allocations). Returns None if EMI idempotent hit."""
    if event_type == "EMI" and period_key:
        existing = (
            await session.execute(
                select(DebtPaymentEvent).where(
                    DebtPaymentEvent.debt_id == debt_id,
                    DebtPaymentEvent.period_key == period_key,
                    DebtPaymentEvent.event_type == "EMI",
                    DebtPaymentEvent.status == "FINALIZED",
                )
            )
        ).scalar_one_or_none()
        if existing:
            return None

    event = DebtPaymentEvent(
        debt_id=debt_id,
        event_type=event_type,
        period_key=period_key,
        scheduled_amount=scheduled_amount,
        actual_amount=actual_amount,
        principal_amount=principal,
        interest_amount=interest,
        fee_amount=fees,
        paid_at=paid_at or datetime.now(timezone.utc),
        status="FINALIZED",
        paid_externally=paid_externally,
        job_id=job_id,
        part_payment_mode=part_payment_mode,
        underpayment_policy=underpayment_policy,
        overpayment_policy=overpayment_policy,
        note=note,
        created_by_user_id=created_by,
    )
    session.add(event)
    await session.flush()

    for ln in allocations or []:
        session.add(
            DebtPaymentAllocation(
                payment_event_id=event.id,
                pool_type=ln["pool_type"],
                family_id=ln.get("family_id"),
                user_id=ln.get("user_id"),
                amount=Decimal(str(ln["amount"])),
            )
        )
    await session.flush()
    return event


async def _post_payment_sync(
    session: AsyncSession,
    debt: Debt,
    *,
    event_type: str,
    amount: Decimal,
    principal: Decimal,
    interest: Decimal,
    period_key: str | None,
    job_id: UUID | None,
    paid_externally: bool,
    old_real_remaining: Decimal,
    new_real_remaining: Decimal,
    allocations: list[dict] | None,
    part_payment_mode: str | None = None,
    note: str | None = None,
    underpayment_policy: str | None = None,
    overpayment_policy: str | None = None,
    scheduled_amount: Decimal | None = None,
) -> DebtPaymentEvent | None:
    await _sync_primary_family_view_display(
        session,
        debt,
        old_real_remaining=old_real_remaining,
        new_real_remaining=new_real_remaining,
    )
    return await finalize_payment_event(
        session,
        debt.id,
        event_type=event_type,
        period_key=period_key,
        scheduled_amount=scheduled_amount if scheduled_amount is not None else (amount if event_type == "EMI" else None),
        actual_amount=amount,
        principal=principal,
        interest=interest,
        fees=_ZERO,
        paid_at=datetime.now(timezone.utc),
        paid_externally=paid_externally,
        job_id=job_id,
        allocations=allocations,
        part_payment_mode=part_payment_mode,
        underpayment_policy=underpayment_policy,
        overpayment_policy=overpayment_policy,
        note=note,
    )


def _split_lines_to_alloc_dicts(lines: list[SplitLine] | None) -> list[dict] | None:
    if not lines:
        return None
    return [
        {
            "pool_type": ln.pool_type,
            "family_id": ln.family_id,
            "user_id": ln.user_id,
            "amount": ln.amount,
        }
        for ln in lines
    ]


# ---------------------------------------------------------------------------
# Apply EMI (called from jobs.py)
# ---------------------------------------------------------------------------


async def apply_debt_emi(
    session: AsyncSession,
    debt: Debt,
    job: ScheduledJob,
    *,
    skip_funding: bool = False,
    paid_externally: bool = False,
    allocations: list[SplitLine] | None = None,
    underpayment_policy: str | None = None,
    overpayment_policy: str | None = None,
) -> None:
    """Apply one EMI: debit pools, update canonical debt, and finalize the event.
    Use skip_funding=True when caller already executed funding (ACCEPT_WITH_SPLITS)
    or recorded an external payment (PAID_EXTERNALLY). Pass allocations for the event.
    job.amount is the authoritative payment amount for this period (supports ADJUST_AMOUNT).
    """
    from app.core.constants import JOB_STATUS_APPLIED

    if job.status == JOB_STATUS_APPLIED:
        logger.info("Job %s already APPLIED; skipping EMI apply", job.id)
        return

    if job.period_key:
        existing = (
            await session.execute(
                select(DebtPaymentEvent).where(
                    DebtPaymentEvent.debt_id == debt.id,
                    DebtPaymentEvent.period_key == job.period_key,
                    DebtPaymentEvent.event_type == "EMI",
                    DebtPaymentEvent.status == "FINALIZED",
                )
            )
        ).scalar_one_or_none()
        if existing:
            logger.info(
                "EMI already FINALIZED for debt=%s period=%s; skipping",
                debt.id,
                job.period_key,
            )
            job.status = JOB_STATUS_APPLIED
            return

    scheduled_emi = debt.emi_amount or job.amount or _ZERO
    # Job amount wins for adjusted/partial payments
    emi = job.amount if job.amount is not None else scheduled_emi
    source_type = _source_type(debt)
    when = datetime.now(timezone.utc)
    old_real_remaining = _real_remaining(debt)

    debit_lines: list[SplitLine] | None = allocations
    if not skip_funding:
        fs = FundingService(session)
        if paid_externally:
            await fs.execute_paid_externally(
                entity_type=source_type,
                entity_id=debt.id,
                amount=emi,
                job_id=job.id,
                description=f"EMI paid externally — {debt.debt_name} ({job.period_key})",
                occurred_at=when,
            )
        else:
            split_plan = await fs.load_split_plan(SOURCE_DEBT, debt.id)

            active_lines = []
            if split_plan:
                for sl in split_plan:
                    obl = sl.obligation_remaining
                    # Treat None as still active (legacy plans).
                    if obl is not None and obl <= _ZERO:
                        continue
                    share = sl.amount
                    if obl is not None:
                        share = min(share, obl)
                    if share <= _ZERO:
                        continue
                    active_lines.append((sl, share))

            plan_total = sum((share for _, share in active_lines), _ZERO)
            use_plan = bool(active_lines) and abs(plan_total - emi) < Decimal("0.02")
            # If some payers fulfilled, scale remaining shares to cover EMI when possible,
            # otherwise debit only active shares and take the shortfall from defaults later.
            if active_lines and not use_plan and plan_total > _ZERO:
                # Debit active shares as-is (may be less than EMI) — underpayment handled elsewhere.
                use_plan = True
                emi = plan_total

            if use_plan and active_lines:
                debit_lines = [
                    SplitLine(
                        pool_type=sl.pool_type,
                        amount=share,
                        family_id=sl.family_id,
                        user_id=sl.user_id,
                    )
                    for sl, share in active_lines
                ]
                await fs.execute_debit(
                    debit_lines,
                    emi,
                    ledger_source_type=LEDGER_SOURCE_DEBT_EMI,
                    entity_type=source_type,
                    entity_id=debt.id,
                    job_id=job.id,
                    description=f"EMI — {debt.debt_name} ({job.period_key})",
                    occurred_at=when,
                )
                # Reduce each payer's obligation by what was debited.
                for sl, share in active_lines:
                    if sl.obligation_remaining is not None:
                        sl.obligation_remaining = max(
                            _ZERO, sl.obligation_remaining - share
                        )
            elif not active_lines and split_plan:
                logger.warning(
                    "All payers fulfilled for debt=%s but EMI still due; notifying via underpayment",
                    debt.id,
                )
                pool_ref = _default_pool_ref(debt)
                ledger = SavingsLedgerService(session)
                await ledger.apply_movement(
                    pool_ref,
                    emi,
                    LEDGER_OUT,
                    LEDGER_SOURCE_DEBT_EMI,
                    source_id=debt.id,
                    description=f"EMI (no active payers) — {debt.debt_name} ({job.period_key})",
                    occurred_at=when,
                )
            else:
                pool_ref = _default_pool_ref(debt)
                ledger = SavingsLedgerService(session)
                await ledger.apply_movement(
                    pool_ref,
                    emi,
                    LEDGER_OUT,
                    LEDGER_SOURCE_DEBT_EMI,
                    source_id=debt.id,
                    description=f"EMI — {debt.debt_name} ({job.period_key})",
                    occurred_at=when,
                )

    interest_part, principal_part = split_emi(
        emi,
        old_real_remaining,
        debt.interest_rate or 0.0,
        debt.interest_type or INTEREST_NONE,
        debt.compounding_frequency or "MONTHLY",
    )

    new_real_remaining = max(_ZERO, old_real_remaining - principal_part)

    debt.remaining_amount = new_real_remaining

    debt.total_paid = (debt.total_paid or _ZERO) + emi
    debt.emi_next_date = advance_next_date(
        debt.emi_next_date, **_emi_advance_kwargs(debt)
    )

    await _check_completion(session, debt)

    await _post_payment_sync(
        session,
        debt,
        event_type="EMI",
        amount=emi,
        principal=principal_part,
        interest=interest_part,
        period_key=job.period_key,
        job_id=job.id,
        paid_externally=paid_externally,
        old_real_remaining=old_real_remaining,
        new_real_remaining=new_real_remaining,
        allocations=_split_lines_to_alloc_dicts(debit_lines),
        note=f"EMI {job.period_key}",
        underpayment_policy=underpayment_policy,
        overpayment_policy=overpayment_policy,
        scheduled_amount=scheduled_emi,
    )

    from app.scheduler.debt_cron import create_or_replace_next_debt_job

    await create_or_replace_next_debt_job(session, debt, source_type)


async def _check_completion(
    session: AsyncSession,
    debt: Debt,
) -> None:
    real_remaining = _real_remaining(debt)
    if real_remaining > _ZERO:
        return

    source_type = _source_type(debt)
    bucket_svc = DefaultBucketService(session)
    open_total = await bucket_svc.total_open(source_type, debt.id)
    if open_total > _ZERO:
        logger.info("Debt %s has open defaults (%s); deferring PAID", debt.id, open_total)
        return

    debt.status = "PAID"
    debt.completed_at = datetime.now(timezone.utc)

    await session.execute(
        update(ScheduledJob)
        .where(
            ScheduledJob.source_type == SOURCE_DEBT,
            ScheduledJob.source_id == debt.id,
            ScheduledJob.status.in_([JOB_STATUS_SCHEDULED, JOB_STATUS_AWAITING_CONFIRMATION]),
        )
        .values(status=JOB_STATUS_CANCELLED)
    )
    await session.execute(
        update(Notification)
        .where(
            Notification.related_entity_type == SOURCE_DEBT,
            Notification.related_entity_id == debt.id,
            Notification.status == "UNREAD",
        )
        .values(status=NOTIF_STATUS_DISMISSED)
    )

    try:
        from app.utils.finance_emails import send_debt_completed_email
        from app.api.routes.user.model import UserBase

        owner_id = debt.owner_user_id
        if owner_id:
            owner = (
                await session.execute(select(UserBase).where(UserBase.id == owner_id))
            ).scalar_one_or_none()
            if owner:
                await send_debt_completed_email(
                    session,
                    owner_email=owner.email,
                    debt_name=debt.debt_name,
                    total_paid=debt.total_paid or _ZERO,
                    family_id=debt.primary_family_id,
                    entity_id=debt.id,
                )
    except Exception:
        logger.exception("Failed to send debt-completed email for %s", debt.id)

    await session.flush()


# ---------------------------------------------------------------------------
# Part payment + simulate
# ---------------------------------------------------------------------------


def _compute_part_payment_result(
    debt: Debt,
    *,
    amount: Decimal,
    mode: str,
    target_emi: Decimal | None = None,
    target_tenure: int | None = None,
) -> dict:
    """Pure computation of part-payment outcome (no mutation)."""
    mode = _normalize_part_mode(mode)
    real_remaining = _real_remaining(debt)
    old_emi = debt.emi_amount or _ZERO
    remaining_periods = debt.tenure_months or 12
    rate = debt.interest_rate or 0.0
    itype = debt.interest_type or INTEREST_NONE

    if mode == "FORECLOSURE":
        if amount < real_remaining:
            raise ValueError(
                f"FORECLOSURE requires paying full remaining ({real_remaining})"
            )
        return {
            "old_remaining": real_remaining,
            "new_remaining": _ZERO,
            "old_emi": old_emi,
            "new_emi": _ZERO,
            "new_periods": 0,
            "note": "Foreclosed — debt paid in full",
            "interest_saved_estimate": _ZERO,
            "payoff_date": datetime.now(timezone.utc),
            "periods_cleared": 0,
            "emi_next_date": None,
            "end_date": datetime.now(timezone.utc),
        }

    if amount > real_remaining:
        raise ValueError(f"Part payment ({amount}) exceeds remaining ({real_remaining})")

    if mode == "CLEAR_UPCOMING" and old_emi > _ZERO:
        periods_cleared = int(amount // old_emi)
        new_remaining = max(_ZERO, real_remaining - amount)
        next_date = debt.emi_next_date
        if periods_cleared > 0 and next_date:
            for _ in range(periods_cleared):
                next_date = advance_next_date(next_date, **_emi_advance_kwargs(debt))
        end_date = debt.end_date
        if next_date and remaining_periods > 0:
            end = next_date
            for _ in range(max(0, remaining_periods - 1)):
                end = advance_next_date(end, **_emi_advance_kwargs(debt))
            end_date = end
        leftover = amount - (old_emi * periods_cleared)
        note = (
            f"Advanced {periods_cleared} installment(s)"
            + (f"; {leftover} leftover to principal" if leftover > 0 else "")
        )
        return {
            "old_remaining": real_remaining,
            "new_remaining": new_remaining,
            "old_emi": old_emi,
            "new_emi": old_emi,
            "new_periods": remaining_periods,
            "note": note,
            "interest_saved_estimate": _ZERO,
            "payoff_date": end_date,
            "periods_cleared": periods_cleared,
            "emi_next_date": next_date,
            "end_date": end_date,
        }

    new_remaining = max(_ZERO, real_remaining - amount)

    if mode == "REDUCE_BOTH":
        new_emi = target_emi if target_emi is not None else old_emi
        new_periods = target_tenure if target_tenure is not None else remaining_periods
        if target_emi is None and target_tenure is None:
            raise ValueError("REDUCE_BOTH requires target_emi and/or target_tenure")
        if target_emi is not None and target_tenure is None and new_emi > _ZERO:
            # Derive tenure from target EMI
            result = recompute_after_part_payment(
                new_remaining, new_emi, rate, itype, remaining_periods, "REDUCE_TENURE"
            )
            new_periods = result["new_periods"]
            note = "EMI and tenure adjusted"
        elif target_tenure is not None and target_emi is None:
            new_emi = compute_emi(new_remaining, rate, new_periods, itype)
            note = "EMI and tenure adjusted"
        else:
            note = "EMI and tenure set to targets"
        end_date = debt.end_date
        if debt.emi_next_date and new_periods > 0:
            end = debt.emi_next_date
            for _ in range(new_periods - 1):
                end = advance_next_date(end, **_emi_advance_kwargs(debt))
            end_date = end
        interest_saved = max(_ZERO, (old_emi * remaining_periods) - (new_emi * new_periods) - amount)
        return {
            "old_remaining": real_remaining,
            "new_remaining": new_remaining,
            "old_emi": old_emi,
            "new_emi": new_emi,
            "new_periods": new_periods,
            "note": note,
            "interest_saved_estimate": _round2(interest_saved),
            "payoff_date": end_date,
            "periods_cleared": 0,
            "emi_next_date": debt.emi_next_date,
            "end_date": end_date,
        }

    result = recompute_after_part_payment(
        new_remaining, old_emi, rate, itype, remaining_periods, mode
    )
    new_emi = result["new_emi"]
    new_periods = result["new_periods"]
    end_date = debt.end_date
    if mode == "REDUCE_TENURE" and debt.emi_next_date and new_periods > 0:
        end = debt.emi_next_date
        for _ in range(new_periods - 1):
            end = advance_next_date(end, **_emi_advance_kwargs(debt))
        end_date = end
    interest_saved = max(
        _ZERO, (old_emi * remaining_periods) - (new_emi * new_periods) - amount
    )
    return {
        "old_remaining": real_remaining,
        "new_remaining": new_remaining,
        "old_emi": old_emi,
        "new_emi": new_emi,
        "new_periods": new_periods,
        "note": result["note"],
        "interest_saved_estimate": _round2(interest_saved),
        "payoff_date": end_date,
        "periods_cleared": 0,
        "emi_next_date": debt.emi_next_date,
        "end_date": end_date,
    }


def simulate_part_payment(
    debt: Debt,
    *,
    amount: Decimal,
    mode: str = "REDUCE_TENURE",
    target_emi: Decimal | None = None,
    target_tenure: int | None = None,
) -> dict:
    """Dry-run part payment — returns old/new EMI, tenure, interest saved, payoff date."""
    if amount <= _ZERO and _normalize_part_mode(mode) != "FORECLOSURE":
        raise ValueError("Part payment amount must be positive")
    return _compute_part_payment_result(
        debt,
        amount=amount,
        mode=mode,
        target_emi=target_emi,
        target_tenure=target_tenure,
    )


async def apply_part_payment(
    session: AsyncSession,
    debt: Debt,
    *,
    amount: Decimal,
    mode: PartPaymentMode | str = "REDUCE_TENURE",
    split_lines: list[SplitLine] | None = None,
    paid_externally: bool = False,
    target_emi: Decimal | None = None,
    target_tenure: int | None = None,
) -> dict:
    """Apply a lump-sum part payment. Returns before/after summary."""
    mode = _normalize_part_mode(mode)
    if amount <= _ZERO and mode != "FORECLOSURE":
        raise ValueError("Part payment amount must be positive")

    real_remaining = _real_remaining(debt)
    if mode == "FORECLOSURE":
        amount = real_remaining
    elif amount > real_remaining:
        raise ValueError(f"Part payment ({amount}) exceeds remaining ({real_remaining})")

    source_type = _source_type(debt)
    when = datetime.now(timezone.utc)
    old_real_remaining = real_remaining

    fs = FundingService(session)
    used_lines: list[SplitLine] | None = None
    if paid_externally:
        await fs.execute_paid_externally(
            entity_type=source_type,
            entity_id=debt.id,
            amount=amount,
            description=f"Part payment (paid externally) — {debt.debt_name}",
            occurred_at=when,
        )
    elif split_lines:
        # Funding splits must sum to the payment amount (scale if weights/EMI shares sent).
        funding = _scale_split_lines_to_amount(split_lines, amount)
        used_lines = funding
        await fs.execute_debit(
            funding,
            amount,
            ledger_source_type=LEDGER_SOURCE_DEBT_PART_PAYMENT,
            entity_type=source_type,
            entity_id=debt.id,
            description=f"Part payment — {debt.debt_name}",
            occurred_at=when,
        )
    else:
        plan = await fs.load_split_plan(SOURCE_DEBT, debt.id)
        if plan:
            plan_lines = [
                SplitLine(
                    pool_type=sl.pool_type,
                    amount=sl.amount,
                    family_id=sl.family_id,
                    user_id=sl.user_id,
                )
                for sl in plan
                if sl.amount and sl.amount > _ZERO
            ]
            if plan_lines:
                used_lines = _scale_split_lines_to_amount(plan_lines, amount)
                await fs.execute_debit(
                    used_lines,
                    amount,
                    ledger_source_type=LEDGER_SOURCE_DEBT_PART_PAYMENT,
                    entity_type=source_type,
                    entity_id=debt.id,
                    description=f"Part payment — {debt.debt_name}",
                    occurred_at=when,
                )
            else:
                pool_ref = _default_pool_ref(debt)
                ledger = SavingsLedgerService(session)
                await ledger.apply_movement(
                    pool_ref,
                    amount,
                    LEDGER_OUT,
                    LEDGER_SOURCE_DEBT_PART_PAYMENT,
                    source_id=debt.id,
                    description=f"Part payment — {debt.debt_name}",
                    occurred_at=when,
                )
        else:
            pool_ref = _default_pool_ref(debt)
            ledger = SavingsLedgerService(session)
            await ledger.apply_movement(
                pool_ref,
                amount,
                LEDGER_OUT,
                LEDGER_SOURCE_DEBT_PART_PAYMENT,
                source_id=debt.id,
                description=f"Part payment — {debt.debt_name}",
                occurred_at=when,
            )

    computed = _compute_part_payment_result(
        debt,
        amount=amount,
        mode=mode,
        target_emi=target_emi,
        target_tenure=target_tenure,
    )
    new_remaining = computed["new_remaining"]

    if mode == "CLEAR_UPCOMING":
        if computed.get("emi_next_date") is not None:
            debt.emi_next_date = computed["emi_next_date"]
    elif mode == "FORECLOSURE":
        debt.emi_amount = _ZERO
        debt.has_emi = False
        debt.emi_next_date = None
        debt.tenure_months = 0
    elif mode == "REDUCE_EMI":
        debt.emi_amount = computed["new_emi"]
    elif mode == "REDUCE_TENURE":
        debt.tenure_months = computed["new_periods"]
        if computed.get("end_date") is not None:
            debt.end_date = computed["end_date"]
    elif mode == "REDUCE_BOTH":
        debt.emi_amount = computed["new_emi"]
        debt.tenure_months = computed["new_periods"]
        if computed.get("end_date") is not None:
            debt.end_date = computed["end_date"]

    debt.remaining_amount = new_remaining

    debt.total_paid = (debt.total_paid or _ZERO) + amount

    await session.flush()
    await _check_completion(session, debt)

    await _post_payment_sync(
        session,
        debt,
        event_type="PART_PAYMENT",
        amount=amount,
        principal=amount,
        interest=_ZERO,
        period_key=None,
        job_id=None,
        paid_externally=paid_externally,
        old_real_remaining=old_real_remaining,
        new_real_remaining=new_remaining,
        allocations=_split_lines_to_alloc_dicts(used_lines),
        part_payment_mode=mode,
        note=computed["note"],
    )

    from app.scheduler.debt_cron import cancel_pending_debt_jobs, create_or_replace_next_debt_job

    if debt.status == "ACTIVE" and debt.has_emi:
        await cancel_pending_debt_jobs(session, debt.id, source_type)
        if debt.emi_next_date:
            await create_or_replace_next_debt_job(session, debt, source_type)

    return {
        "old_remaining": computed["old_remaining"],
        "new_remaining": new_remaining,
        "old_emi": computed["old_emi"],
        "new_emi": computed["new_emi"],
        "new_periods": computed["new_periods"],
        "note": computed["note"],
        "interest_saved_estimate": computed.get("interest_saved_estimate", _ZERO),
        "payoff_date": computed.get("payoff_date"),
    }


# ---------------------------------------------------------------------------
# DebtService — CRUD + scope-aware listing
# ---------------------------------------------------------------------------


class DebtService:
    """Service wrapper exposing debt CRUD, part-payment and default-bucket ops."""

    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def list_debts(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext | None = None,
        status: str | None = "ACTIVE",
        q: str | None = None,
        type: str | None = None,
        owner_user_id: UUID | None = None,
        has_emi: bool | None = None,
        is_masked: bool | None = None,
    ) -> tuple[list[tuple[DebtRow, bool]], int]:
        """List family-scope debts only (via DebtScopeView)."""
        stmt = (
            select(Debt, DebtScopeView)
            .join(DebtScopeView, DebtScopeView.debt_id == Debt.id)
            .where(
                DebtScopeView.scope_kind == "FAMILY",
                DebtScopeView.family_id == family_id,
            )
        )
        if scope_ctx is None:
            stmt = stmt.where(DebtScopeView.user_id.is_(None))
        else:
            stmt = stmt.where(
                or_(
                    DebtScopeView.user_id.is_(None),
                    DebtScopeView.user_id == scope_ctx.user_id,
                )
            )
        if status:
            stmt = stmt.where(Debt.status == status)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(Debt.debt_name.ilike(like), DebtScopeView.display_name.ilike(like))
            )
        if type:
            stmt = stmt.where(Debt.type == type)
        if owner_user_id:
            stmt = stmt.where(Debt.owner_user_id == owner_user_id)
        if has_emi is not None:
            stmt = stmt.where(Debt.has_emi.is_(has_emi))
        if is_masked is not None:
            stmt = stmt.where(DebtScopeView.is_masked.is_(is_masked))

        raw_rows = list((await self.pg_session.execute(stmt)).all())
        by_debt: dict[UUID, tuple[Debt, DebtScopeView]] = {}
        for debt, view in raw_rows:
            current = by_debt.get(debt.id)
            if current is None or (
                scope_ctx is not None and view.user_id == scope_ctx.user_id
            ):
                by_debt[debt.id] = (debt, view)

        viewer = scope_ctx.user_id if scope_ctx else None
        visible: list[tuple[DebtRow, bool]] = []
        for debt, view in by_debt.values():
            if view.excluded:
                continue
            owner = debt.owner_user_id
            access = view.access_level or "FAMILY"
            has_viewer_override = (
                scope_ctx is not None and view.user_id == scope_ctx.user_id
            )
            if scope_ctx is not None and not has_viewer_override:
                if owner != scope_ctx.user_id:
                    if access == "PRIVATE":
                        continue
                    if access == ACCESS_SELECTED:
                        continue
                    elif access not in ("FAMILY", ACCESS_SELECTED):
                        if not can_view_scoped_entity(
                            scope_ctx,
                            scope_type="FAMILY",
                            owner_user_id=owner,
                            access_level=access,
                            entity_id=debt.id,
                        ):
                            continue

            lines = await _load_debt_split_line_dicts(self.pg_session, debt.id)
            row = build_debt_row(
                debt, view, viewer_user_id=viewer, split_lines=lines
            )
            visible.append((row, False))

        visible.sort(key=lambda x: x[0].created_at, reverse=True)
        total = len(visible)
        return visible[pagination.offset : pagination.offset + pagination.page_size], total

    async def list_debt_history(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext | None = None,
    ) -> tuple[list[tuple[DebtRow, bool]], int]:
        return await self.list_debts(
            family_id, pagination, scope_ctx=scope_ctx, status="PAID"
        )

    async def list_personal_debts(
        self,
        user_id: UUID,
        pagination: PaginationParams,
        *,
        status: str | None = "ACTIVE",
        q: str | None = None,
        type: str | None = None,
        has_emi: bool | None = None,
    ) -> tuple[list[DebtRow], int]:
        stmt = (
            select(Debt, DebtScopeView)
            .join(DebtScopeView, DebtScopeView.debt_id == Debt.id)
            .where(
                DebtScopeView.scope_kind == "PERSONAL",
                DebtScopeView.user_id == user_id,
            )
        )
        if status:
            stmt = stmt.where(Debt.status == status)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(Debt.debt_name.ilike(like), DebtScopeView.display_name.ilike(like))
            )
        if type:
            stmt = stmt.where(Debt.type == type)
        if has_emi is not None:
            stmt = stmt.where(Debt.has_emi.is_(has_emi))
        rows = list((await self.pg_session.execute(stmt)).all())
        items: list[DebtRow] = []
        for debt, view in rows:
            lines = await _load_debt_split_line_dicts(self.pg_session, debt.id)
            items.append(
                build_debt_row(debt, view, viewer_user_id=user_id, split_lines=lines)
            )
        items.sort(key=lambda d: d.created_at, reverse=True)
        total = len(items)
        return items[pagination.offset : pagination.offset + pagination.page_size], total

    async def get_personal_debt(
        self, debt_id: UUID, user_id: UUID
    ) -> DebtRow | None:
        stmt = (
            select(Debt, DebtScopeView)
            .join(DebtScopeView, DebtScopeView.debt_id == Debt.id)
            .where(
                Debt.id == debt_id,
                DebtScopeView.scope_kind == "PERSONAL",
                DebtScopeView.user_id == user_id,
            )
        )
        result = (await self.pg_session.execute(stmt)).first()
        if not result:
            # Fallback: owner of canonical debt
            debt = (
                await self.pg_session.execute(
                    select(Debt).where(Debt.id == debt_id, Debt.owner_user_id == user_id)
                )
            ).scalar_one_or_none()
            if not debt:
                return None
            view = (
                await self.pg_session.execute(
                    select(DebtScopeView).where(
                        DebtScopeView.debt_id == debt.id,
                        DebtScopeView.scope_kind == "PERSONAL",
                    )
                )
            ).scalar_one_or_none()
            lines = await _load_debt_split_line_dicts(self.pg_session, debt.id)
            all_views = list(
                (
                    await self.pg_session.execute(
                        select(DebtScopeView).where(DebtScopeView.debt_id == debt.id)
                    )
                ).scalars().all()
            )
            return build_debt_row(
                debt,
                view,
                viewer_user_id=user_id,
                all_views=all_views if debt.owner_user_id == user_id else None,
                split_lines=lines,
            )
        debt, view = result
        lines = await _load_debt_split_line_dicts(self.pg_session, debt.id)
        all_views = None
        if debt.owner_user_id == user_id:
            all_views = list(
                (
                    await self.pg_session.execute(
                        select(DebtScopeView).where(DebtScopeView.debt_id == debt.id)
                    )
                ).scalars().all()
            )
        return build_debt_row(
            debt,
            view,
            viewer_user_id=user_id,
            all_views=all_views,
            split_lines=lines,
        )

    async def create_personal_debt(
        self, user_id: UUID, family_id: UUID, request: DebtCreateRequest
    ) -> DebtRow:
        request = request.model_copy(update={"is_personal": True})
        debt, _ = await self.create_debt(family_id, user_id, request)
        return debt

    async def _allowed_funding_family_ids(self, owner_user_id: UUID) -> set[UUID]:
        """Families the owner belongs to, plus families with an active relationship."""
        from app.api.routes.family.model import FamilyRelationship
        from app.api.routes.family_relationship.family_relationship_service import (
            RELATIONSHIP_ACTIVE,
        )

        owner_family_ids = set(
            (
                await self.pg_session.execute(
                    select(UserFamilyLink.family_id).where(
                        UserFamilyLink.user_id == owner_user_id
                    )
                )
            ).scalars().all()
        )
        allowed = set(owner_family_ids)
        if owner_family_ids:
            related_rows = (
                await self.pg_session.execute(
                    select(
                        FamilyRelationship.family_a_id,
                        FamilyRelationship.family_b_id,
                    ).where(
                        FamilyRelationship.status == RELATIONSHIP_ACTIVE,
                        or_(
                            FamilyRelationship.family_a_id.in_(owner_family_ids),
                            FamilyRelationship.family_b_id.in_(owner_family_ids),
                        ),
                    )
                )
            ).all()
            for a_id, b_id in related_rows:
                allowed.add(a_id)
                allowed.add(b_id)
        return allowed

    async def _validate_personal_payer(
        self, owner_user_id: UUID, payer_user_id: UUID, allowed_family_ids: set[UUID]
    ) -> None:
        """Owner or any member of an allowed funding family may contribute personal savings."""
        if payer_user_id == owner_user_id:
            return
        if not allowed_family_ids:
            raise PermissionError(
                "Personal savings may only come from the owner or members of linked families"
            )
        link = (
            await self.pg_session.execute(
                select(UserFamilyLink.user_id).where(
                    UserFamilyLink.user_id == payer_user_id,
                    UserFamilyLink.family_id.in_(allowed_family_ids),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if link is None:
            raise PermissionError(
                "Personal savings may only come from the owner or members of linked families"
            )

    async def _validate_split_plan_access(
        self, owner_user_id: UUID, split_lines: list[dict]
    ) -> None:
        """Owner/linked-family personal pools, member families, or related families may pay."""
        from sqlalchemy import and_

        from app.api.routes.family.model import FamilyRelationship
        from app.api.routes.family_relationship.family_relationship_service import (
            RELATIONSHIP_ACTIVE,
        )

        allowed_family_ids = await self._allowed_funding_family_ids(owner_user_id)
        owner_family_ids = set(
            (
                await self.pg_session.execute(
                    select(UserFamilyLink.family_id).where(
                        UserFamilyLink.user_id == owner_user_id
                    )
                )
            ).scalars().all()
        )
        for line in split_lines:
            pool_type = line["pool_type"]
            if pool_type == "PERSONAL":
                line_user_id = line.get("user_id") or owner_user_id
                await self._validate_personal_payer(
                    owner_user_id, line_user_id, allowed_family_ids
                )
                line["user_id"] = line_user_id
                line["family_id"] = None
                continue

            family_id = line.get("family_id")
            if family_id is None:
                raise ValueError(f"family_id is required for {pool_type}")
            if family_id in allowed_family_ids:
                continue
            relation = (
                await self.pg_session.execute(
                    select(FamilyRelationship.id).where(
                        FamilyRelationship.status == RELATIONSHIP_ACTIVE,
                        or_(
                            and_(
                                FamilyRelationship.family_a_id.in_(owner_family_ids),
                                FamilyRelationship.family_b_id == family_id,
                            ),
                            and_(
                                FamilyRelationship.family_b_id.in_(owner_family_ids),
                                FamilyRelationship.family_a_id == family_id,
                            ),
                        ),
                    )
                )
            ).scalar_one_or_none()
            if relation is None:
                raise PermissionError(
                    f"Family {family_id} is not a member or accepted relationship family"
                )

    async def upsert_split_plan(
        self, debt: Debt, split_lines: list[dict]
    ) -> None:
        await self._validate_split_plan_access(debt.owner_user_id, split_lines)
        fs = FundingService(self.pg_session)
        await fs.save_split_plan(SOURCE_DEBT, debt.id, split_lines)
        await self.pg_session.commit()

    async def create_debt(
        self, family_id: UUID, user_id: UUID, request: DebtCreateRequest
    ) -> tuple[DebtRow, bool]:
        validate_debt_type(request.type)

        is_personal = bool(request.is_personal)
        is_masked = bool(request.is_masked) and not is_personal
        owner_id = (
            user_id
            if is_personal
            else (request.debt_in_the_name_of or user_id)
        )

        # When masked: request.total_amount is DISPLAY; real_* is CANONICAL.
        if is_masked:
            if request.real_total_amount is None:
                raise ValueError("real_total_amount is required when is_masked")
            canonical_total = request.real_total_amount
            canonical_remaining = (
                request.real_remaining_amount
                if request.real_remaining_amount is not None
                else request.real_total_amount
            )
            display_total = request.total_amount
            display_remaining = (
                request.remaining_amount
                if request.remaining_amount is not None
                else request.total_amount
            )
            validate_mask_fields(
                is_masked=True,
                display_total=display_total,
                display_remaining=display_remaining,
                display_emi=request.emi_amount,
                display_rate=request.interest_rate,
                has_emi=request.has_emi,
                has_interest=request.has_interest,
            )
            interest = normalize_interest_fields(
                has_interest=request.has_interest,
                interest_type=request.interest_type,
                interest_rate=request.real_interest_rate
                if request.real_interest_rate is not None
                else request.interest_rate,
                compounding_frequency=request.compounding_frequency,
                fixed_fee_amount=request.fixed_fee_amount,
                interest_increase_every=request.interest_increase_every,
                interest_increase_percentage=request.interest_increase_percentage,
                next_interest_increase_date=request.next_interest_increase_date,
            )
            emi = normalize_emi_fields(
                has_emi=request.has_emi,
                principal=canonical_remaining,
                has_interest=interest["has_interest"],
                interest_type=interest["interest_type"],
                interest_rate=interest["interest_rate"],
                compounding_frequency=interest["compounding_frequency"],
                emi_amount=request.real_emi_amount or request.emi_amount,
                emi_every=request.emi_every,
                emi_interval_days=request.emi_interval_days,
                emi_interval_months=request.emi_interval_months,
                emi_interval_years=request.emi_interval_years,
                tenure_months=request.tenure_months,
                emi_next_date=request.emi_next_date,
                requires_confirmation=request.requires_confirmation,
            )
            display_emi = request.emi_amount
            display_rate = request.interest_rate
        else:
            canonical_total = request.total_amount
            canonical_remaining = (
                request.remaining_amount
                if request.remaining_amount is not None
                else request.total_amount
            )
            display_total = canonical_total
            display_remaining = canonical_remaining
            interest = normalize_interest_fields(
                has_interest=request.has_interest,
                interest_type=request.interest_type,
                interest_rate=request.interest_rate,
                compounding_frequency=request.compounding_frequency,
                fixed_fee_amount=request.fixed_fee_amount,
                interest_increase_every=request.interest_increase_every,
                interest_increase_percentage=request.interest_increase_percentage,
                next_interest_increase_date=request.next_interest_increase_date,
            )
            emi = normalize_emi_fields(
                has_emi=request.has_emi,
                principal=canonical_remaining,
                has_interest=interest["has_interest"],
                interest_type=interest["interest_type"],
                interest_rate=interest["interest_rate"],
                compounding_frequency=interest["compounding_frequency"],
                emi_amount=request.emi_amount,
                emi_every=request.emi_every,
                emi_interval_days=request.emi_interval_days,
                emi_interval_months=request.emi_interval_months,
                emi_interval_years=request.emi_interval_years,
                tenure_months=request.tenure_months,
                emi_next_date=request.emi_next_date,
                requires_confirmation=request.requires_confirmation,
            )
            display_emi = emi["emi_amount"]
            display_rate = interest["interest_rate"]

        debt_id = uuid6.uuid7()
        show_breakdown = bool(
            request.show_split_to_family
            if request.showSplitToFamily is None
            else request.showSplitToFamily
        )

        canonical = Debt(
            id=debt_id,
            owner_user_id=owner_id,
            primary_family_id=family_id,
            debt_name=request.debt_name,
            type=request.type,
            status="ACTIVE",
            total_amount=canonical_total,
            remaining_amount=canonical_remaining,
            total_paid=_ZERO,
            has_interest=interest["has_interest"],
            interest_type=interest["interest_type"],
            interest_rate=interest["interest_rate"],
            compounding_frequency=interest["compounding_frequency"],
            fixed_fee_amount=interest["fixed_fee_amount"],
            interest_increase_every=interest["interest_increase_every"],
            interest_increase_percentage=interest["interest_increase_percentage"],
            next_interest_increase_date=interest["next_interest_increase_date"],
            has_emi=emi["has_emi"],
            emi_amount=emi["emi_amount"],
            emi_every=emi["emi_every"],
            emi_interval_days=emi["emi_interval_days"],
            emi_interval_months=emi["emi_interval_months"],
            emi_interval_years=emi["emi_interval_years"],
            tenure_months=emi["tenure_months"],
            emi_next_date=emi["emi_next_date"],
            requires_confirmation=emi["requires_confirmation"],
            bounce_fine_amount=request.bounce_fine_amount or _ZERO,
            allow_auto_default=request.allow_auto_default,
            start_date=request.start_date,
            end_date=request.end_date,
            document_id=request.document_id,
            show_doc_to_all=request.show_doc_to_all,
            doc_viewer_user_ids=request.doc_viewer_user_ids,
        )
        self.pg_session.add(canonical)

        if is_personal:
            view = DebtScopeView(
                debt_id=debt_id,
                scope_kind="PERSONAL",
                family_id=None,
                user_id=owner_id,
                is_primary=True,
                display_name=request.debt_name,
                display_type=request.type,
                display_total_amount=canonical_total,
                display_remaining_amount=canonical_remaining,
                display_emi_amount=emi["emi_amount"],
                display_interest_rate=interest["interest_rate"],
                is_masked=False,
                show_breakdown=False,
                access_level=request.access_level or "PRIVATE",
            )
        else:
            access = request.access_level or "FAMILY"
            view = DebtScopeView(
                debt_id=debt_id,
                scope_kind="FAMILY",
                family_id=family_id,
                user_id=None,
                is_primary=True,
                display_name=request.debt_name,
                display_type=request.type,
                display_total_amount=display_total,
                display_remaining_amount=display_remaining,
                display_emi_amount=display_emi,
                display_interest_rate=display_rate,
                is_masked=is_masked,
                show_breakdown=show_breakdown,
                access_level=access,
            )

        self.pg_session.add(view)
        await self.pg_session.flush()

        if request.splitLines:
            lines = [
                _request_split_line_dict(sl, default_personal_user_id=owner_id)
                for sl in request.splitLines
            ]
            await self._validate_split_plan_access(owner_id, lines)
            fs = FundingService(self.pg_session)
            await fs.save_split_plan(SOURCE_DEBT, debt_id, lines)

        from app.scheduler.debt_cron import create_or_replace_next_debt_job

        await create_or_replace_next_debt_job(self.pg_session, canonical, SOURCE_DEBT)

        # Optional extra scope views from create payload (sharing across families/personal)
        if request.scope_views:
            extra = [
                {
                    "scope_kind": v.scope_kind,
                    "family_id": v.family_id,
                    "user_id": v.user_id,
                    "display_name": v.display_name or request.debt_name,
                    "display_type": v.display_type or request.type,
                    "display_total_amount": v.display_total_amount,
                    "display_remaining_amount": v.display_remaining_amount,
                    "display_emi_amount": v.display_emi_amount,
                    "display_interest_rate": v.display_interest_rate,
                    "is_masked": v.is_masked,
                    "show_breakdown": v.show_breakdown,
                    "access_level": v.access_level,
                }
                for v in request.scope_views
            ]
            # Include the primary view so upsert does not treat it as omitted-only
            extra.insert(
                0,
                {
                    "scope_kind": view.scope_kind,
                    "family_id": view.family_id,
                    "user_id": view.user_id,
                    "display_name": view.display_name,
                    "display_type": view.display_type,
                    "display_total_amount": view.display_total_amount,
                    "display_remaining_amount": view.display_remaining_amount,
                    "display_emi_amount": view.display_emi_amount,
                    "display_interest_rate": view.display_interest_rate,
                    "is_masked": view.is_masked,
                    "show_breakdown": view.show_breakdown,
                    "access_level": view.access_level,
                },
            )
            await self.upsert_scope_views(debt_id, owner_id, extra)
        else:
            await self.pg_session.commit()

        await self.pg_session.refresh(canonical)
        lines = await _load_debt_split_line_dicts(self.pg_session, canonical.id)
        return (
            build_debt_row(
                canonical,
                view,
                viewer_user_id=user_id,
                split_lines=lines,
            ),
            is_personal,
        )

    async def get_debt(
        self, debt_id: UUID, family_id: UUID, *, viewer_user_id: UUID | None = None
    ) -> tuple[DebtRow, bool] | None:
        debt = (
            await self.pg_session.execute(select(Debt).where(Debt.id == debt_id))
        ).scalar_one_or_none()
        if debt is None:
            return None

        family_view_stmt = select(DebtScopeView).where(
            DebtScopeView.debt_id == debt_id,
            DebtScopeView.scope_kind == "FAMILY",
            DebtScopeView.family_id == family_id,
        )
        if viewer_user_id is None:
            family_view_stmt = family_view_stmt.where(
                DebtScopeView.user_id.is_(None)
            )
        else:
            family_view_stmt = family_view_stmt.where(
                or_(
                    DebtScopeView.user_id.is_(None),
                    DebtScopeView.user_id == viewer_user_id,
                )
            )
        family_views = list(
            (
                await self.pg_session.execute(family_view_stmt)
            ).scalars().all()
        )
        family_view = next(
            (view for view in family_views if view.user_id == viewer_user_id),
            next((view for view in family_views if view.user_id is None), None),
        )

        is_owner = viewer_user_id is not None and debt.owner_user_id == viewer_user_id
        if family_view is not None and family_view.excluded:
            return None
        if family_view is None and not is_owner:
            return None
        if family_view is None and is_owner:
            # Owner may view without family scope (e.g. personal-only); still require family match
            if debt.primary_family_id != family_id:
                return None
            personal_view = (
                await self.pg_session.execute(
                    select(DebtScopeView).where(
                        DebtScopeView.debt_id == debt_id,
                        DebtScopeView.scope_kind == "PERSONAL",
                    )
                )
            ).scalar_one_or_none()
            lines = await _load_debt_split_line_dicts(self.pg_session, debt.id)
            all_views = list(
                (
                    await self.pg_session.execute(
                        select(DebtScopeView).where(DebtScopeView.debt_id == debt_id)
                    )
                ).scalars().all()
            )
            return (
                build_debt_row(
                    debt,
                    personal_view,
                    viewer_user_id=viewer_user_id,
                    all_views=all_views,
                    split_lines=lines,
                ),
                True,
            )

        all_views = list(
            (
                await self.pg_session.execute(
                    select(DebtScopeView).where(DebtScopeView.debt_id == debt_id)
                )
            ).scalars().all()
        )
        lines = await _load_debt_split_line_dicts(self.pg_session, debt.id)
        return (
            build_debt_row(
                debt,
                family_view,
                viewer_user_id=viewer_user_id,
                all_views=all_views,
                split_lines=lines,
            ),
            False,
        )

    async def update_debt(
        self, debt: Debt, request: DebtUpdateRequest
    ) -> Debt:
        view = (
            await self.pg_session.execute(
                select(DebtScopeView).where(
                    DebtScopeView.debt_id == debt.id,
                    DebtScopeView.is_primary.is_(True),
                )
            )
        ).scalar_one_or_none()
        is_masked = bool(view and view.is_masked)
        presentation_fields = {
            "splitLines",
            "is_masked",
            "real_total_amount",
            "real_remaining_amount",
            "real_emi_amount",
            "real_interest_rate",
            "show_split_to_family",
            "access_level",
        }
        data = request.model_dump(exclude_none=True, exclude=presentation_fields)
        if is_masked:
            for field in ("total_amount", "remaining_amount", "emi_amount", "interest_rate"):
                data.pop(field, None)
        real_values = {
            "total_amount": request.real_total_amount,
            "remaining_amount": request.real_remaining_amount,
            "emi_amount": request.real_emi_amount,
            "interest_rate": request.real_interest_rate,
        }
        for field, value in real_values.items():
            if value is not None:
                data[field] = value
        for field, value in data.items():
            setattr(debt, field, value)

        # Clear alternative EMI frequency fields on update to keep them mutually exclusive
        if request.emi_every is not None:
            debt.emi_interval_days = None
            debt.emi_interval_months = None
            debt.emi_interval_years = None
        elif any(
            v is not None
            for v in [
                request.emi_interval_days,
                request.emi_interval_months,
                request.emi_interval_years,
            ]
        ):
            debt.emi_every = None

        if request.splitLines is not None:
            lines = [
                _request_split_line_dict(
                    sl, default_personal_user_id=debt.owner_user_id
                )
                for sl in request.splitLines
            ]
            await self._validate_split_plan_access(debt.owner_user_id, lines)
            fs = FundingService(self.pg_session)
            await fs.save_split_plan(SOURCE_DEBT, debt.id, lines)

        if view is not None:
            if request.debt_name is not None:
                view.display_name = request.debt_name
            if request.access_level is not None:
                view.access_level = request.access_level
            if request.is_masked is not None:
                view.is_masked = request.is_masked
            if request.show_split_to_family is not None:
                view.show_breakdown = request.show_split_to_family
            if view.is_masked:
                if request.total_amount is not None:
                    view.display_total_amount = request.total_amount
                if request.remaining_amount is not None:
                    view.display_remaining_amount = request.remaining_amount
                if request.emi_amount is not None:
                    view.display_emi_amount = request.emi_amount
                if request.interest_rate is not None:
                    view.display_interest_rate = request.interest_rate
            else:
                view.display_total_amount = debt.total_amount
                view.display_remaining_amount = debt.remaining_amount
                view.display_emi_amount = debt.emi_amount
                view.display_interest_rate = debt.interest_rate

        from app.scheduler.debt_cron import cancel_pending_debt_jobs, create_or_replace_next_debt_job

        if debt.status == "ACTIVE" and debt.has_emi and debt.emi_next_date:
            await create_or_replace_next_debt_job(
                self.pg_session, debt, _source_type(debt)
            )
        else:
            await cancel_pending_debt_jobs(
                self.pg_session, debt.id, _source_type(debt)
            )

        await self.pg_session.commit()
        await self.pg_session.refresh(debt)
        return debt

    async def contribute_to_balance(
        self,
        debt: Debt,
        *,
        actor_user_id: UUID,
        amount: Decimal,
        pool_type: str | None = None,
        family_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> dict:
        """Payer contribution: debit their pool into debt.balance_for_part_payment."""
        if amount <= _ZERO:
            raise ValueError("Contribution amount must be positive")

        fs = FundingService(self.pg_session)
        plan = await fs.load_split_plan(SOURCE_DEBT, debt.id)
        if not plan:
            raise PermissionError("This debt has no payers configured")

        # Resolve which split line the actor is contributing against.
        matched = None
        for sl in plan:
            if sl.pool_type == "PERSONAL" and sl.user_id == actor_user_id:
                matched = sl
                break
        if matched is None:
            # Family pool: actor must be a member of that family.
            actor_family_ids = set(
                (
                    await self.pg_session.execute(
                        select(UserFamilyLink.family_id).where(
                            UserFamilyLink.user_id == actor_user_id
                        )
                    )
                ).scalars().all()
            )
            for sl in plan:
                if sl.pool_type in ("CURRENT_FAMILY", "OTHER_FAMILY") and sl.family_id:
                    if family_id and sl.family_id == family_id:
                        matched = sl
                        break
                    if sl.family_id in actor_family_ids:
                        matched = sl
                        break
        if matched is None and pool_type:
            for sl in plan:
                if sl.pool_type == pool_type and (
                    (user_id and sl.user_id == user_id)
                    or (family_id and sl.family_id == family_id)
                ):
                    matched = sl
                    break
        if matched is None:
            raise PermissionError(
                "You are not a payer on this debt. Only listed payers can add to the "
                "part-payment balance; only the debt owner can apply a part payment."
            )

        debit_pool_type = pool_type or matched.pool_type
        debit_family_id = family_id or matched.family_id
        debit_user_id = user_id or matched.user_id or actor_user_id
        if debit_pool_type == "PERSONAL":
            debit_user_id = actor_user_id

        when = datetime.now(timezone.utc)
        await fs.execute_debit(
            [
                SplitLine(
                    pool_type=debit_pool_type,
                    amount=amount,
                    family_id=debit_family_id,
                    user_id=debit_user_id if debit_pool_type == "PERSONAL" else None,
                )
            ],
            amount,
            ledger_source_type=LEDGER_SOURCE_DEBT_PART_PAYMENT,
            entity_type=_source_type(debt),
            entity_id=debt.id,
            description=f"Contribution to part-payment balance — {debt.debt_name}",
            occurred_at=when,
        )

        if matched.obligation_remaining is not None:
            matched.obligation_remaining = max(
                _ZERO, matched.obligation_remaining - amount
            )

        debt.balance_for_part_payment = (
            debt.balance_for_part_payment or _ZERO
        ) + amount

        event = DebtPaymentEvent(
            debt_id=debt.id,
            event_type="CONTRIBUTION",
            actual_amount=amount,
            principal_amount=_ZERO,
            interest_amount=_ZERO,
            paid_at=when,
            status="FINALIZED",
            note="Contribution to balance_for_part_payment",
            created_by_user_id=actor_user_id,
        )
        self.pg_session.add(event)
        await self.pg_session.flush()
        self.pg_session.add(
            DebtPaymentAllocation(
                payment_event_id=event.id,
                pool_type=debit_pool_type,
                family_id=debit_family_id,
                user_id=debit_user_id if debit_pool_type == "PERSONAL" else None,
                amount=amount,
            )
        )
        await self.pg_session.commit()
        return {
            "amount": amount,
            "balance_for_part_payment": debt.balance_for_part_payment,
            "obligation_remaining": matched.obligation_remaining,
        }

    async def part_payment(
        self,
        debt: Debt,
        amount: Decimal,
        mode: str,
        *,
        split_lines: list[SplitLine] | None = None,
        paid_externally: bool = False,
        target_emi: Decimal | None = None,
        target_tenure: int | None = None,
        use_balance: bool = False,
        reassignments: list[dict] | None = None,
        actor_user_id: UUID | None = None,
    ) -> dict:
        if actor_user_id is not None:
            require_debt_owner(actor_user_id, debt)
        from_balance = _ZERO
        remainder = amount
        if use_balance:
            bal = debt.balance_for_part_payment or _ZERO
            if bal <= _ZERO:
                raise ValueError("No part-payment balance available")
            from_balance = min(amount, bal)
            remainder = amount - from_balance
            if remainder > _ZERO:
                if paid_externally:
                    # Balance + external remainder: no savings debit.
                    split_lines = None
                    paid_externally = True
                elif split_lines:
                    # Debit only the shortfall; balance covers the rest.
                    funding = _scale_split_lines_to_amount(split_lines, remainder)
                    fs = FundingService(self.pg_session)
                    when = datetime.now(timezone.utc)
                    await fs.execute_debit(
                        funding,
                        remainder,
                        ledger_source_type=LEDGER_SOURCE_DEBT_PART_PAYMENT,
                        entity_type=_source_type(debt),
                        entity_id=debt.id,
                        description=f"Part payment shortfall — {debt.debt_name}",
                        occurred_at=when,
                    )
                    split_lines = None
                    paid_externally = True
                else:
                    raise ValueError(
                        f"Amount ({amount}) exceeds balance_for_part_payment ({bal}). "
                        "Fund the difference via pools or mark it paid outside."
                    )
            else:
                # Fully covered by contributed balance — no new debit.
                paid_externally = True
                split_lines = None

        result = await apply_part_payment(
            self.pg_session,
            debt,
            amount=amount,
            mode=mode,
            split_lines=split_lines,
            paid_externally=paid_externally,
            target_emi=target_emi,
            target_tenure=target_tenure,
        )

        if use_balance and from_balance > _ZERO:
            debt.balance_for_part_payment = max(
                _ZERO, (debt.balance_for_part_payment or _ZERO) - from_balance
            )

        if reassignments is not None:
            if not reassignments:
                raise ValueError("Reassignments required after applying part payment")
            owner_id = debt.owner_user_id
            lines = []
            for raw in reassignments:
                ln = {
                    "pool_type": raw.get("pool_type") or raw.get("poolType"),
                    "family_id": raw.get("family_id") or raw.get("familyId"),
                    "user_id": raw.get("user_id") or raw.get("userId"),
                    "amount": raw.get("amount"),
                    "expected_total": raw.get("expected_total")
                    or raw.get("expectedTotal"),
                    "obligation_remaining": raw.get("obligation_remaining")
                    or raw.get("obligationRemaining"),
                }
                if ln["obligation_remaining"] is None and ln["expected_total"] is not None:
                    ln["obligation_remaining"] = ln["expected_total"]
                lines.append(ln)
            emi_sum = sum((Decimal(str(l["amount"])) for l in lines), _ZERO)
            new_emi = Decimal(str(result.get("new_emi") or debt.emi_amount or 0))
            if debt.has_emi and new_emi > 0 and abs(emi_sum - new_emi) >= Decimal("0.02"):
                raise ValueError(
                    f"Reassigned EMI shares ({emi_sum}) must equal new EMI ({new_emi})"
                )
            obl_sum = sum(
                (
                    Decimal(str(l["obligation_remaining"]))
                    for l in lines
                    if l.get("obligation_remaining") is not None
                ),
                _ZERO,
            )
            new_remaining = Decimal(str(result.get("new_remaining") or 0))
            if lines and all(l.get("obligation_remaining") is not None for l in lines):
                if abs(obl_sum - new_remaining) >= Decimal("0.02"):
                    raise ValueError(
                        f"Reassigned obligations ({obl_sum}) must equal remaining ({new_remaining})"
                    )
            await self._validate_split_plan_access(owner_id, lines)
            fs = FundingService(self.pg_session)
            await fs.save_split_plan(SOURCE_DEBT, debt.id, lines)

            if actor_user_id:
                self.pg_session.add(
                    DebtPaymentEvent(
                        debt_id=debt.id,
                        event_type="OBLIGATION_REASSIGN",
                        actual_amount=_ZERO,
                        paid_at=datetime.now(timezone.utc),
                        status="FINALIZED",
                        note="Payer EMI/obligation reassignment after part payment",
                        created_by_user_id=actor_user_id,
                    )
                )

        await self.pg_session.commit()
        return result

    async def delete_debt(self, debt: Debt) -> None:
        from app.scheduler.debt_cron import cancel_pending_debt_jobs

        await cancel_pending_debt_jobs(self.pg_session, debt.id, SOURCE_DEBT)

        # Refund balance proportionally to contribution allocations if any remain.
        if (debt.balance_for_part_payment or _ZERO) > _ZERO:
            bal = debt.balance_for_part_payment
            contribs = list(
                (
                    await self.pg_session.execute(
                        select(DebtPaymentEvent).where(
                            DebtPaymentEvent.debt_id == debt.id,
                            DebtPaymentEvent.event_type == "CONTRIBUTION",
                            DebtPaymentEvent.status == "FINALIZED",
                        )
                    )
                ).scalars().all()
            )
            total_contrib = sum((c.actual_amount for c in contribs), _ZERO)
            if total_contrib > _ZERO and contribs:
                for c in contribs:
                    share = _round2(bal * (c.actual_amount / total_contrib))
                    if share <= _ZERO:
                        continue
                    alloc = (
                        await self.pg_session.execute(
                            select(DebtPaymentAllocation).where(
                                DebtPaymentAllocation.payment_event_id == c.id
                            )
                        )
                    ).scalar_one_or_none()
                    if alloc is None:
                        continue
                    # Credit back via negative debit (IN movement).
                    ledger = SavingsLedgerService(self.pg_session)
                    from app.core.constants import LEDGER_IN

                    pool = SplitLine(
                        pool_type=alloc.pool_type,
                        amount=share,
                        family_id=alloc.family_id,
                        user_id=alloc.user_id,
                    ).to_pool_ref()
                    await ledger.apply_movement(
                        pool,
                        share,
                        LEDGER_IN,
                        LEDGER_SOURCE_DEBT_PART_PAYMENT,
                        source_id=debt.id,
                        description=f"Refund unused part-payment balance — {debt.debt_name}",
                    )
            debt.balance_for_part_payment = _ZERO

        debt.status = "CANCELLED"
        debt.has_emi = False
        debt.emi_next_date = None
        await self.pg_session.commit()

    async def list_defaults(
        self, debt: Debt | DebtRow, is_personal: bool
    ) -> tuple[list, Decimal]:
        debt_id = debt.id
        svc = DefaultBucketService(self.pg_session)
        items = await svc.list_open(SOURCE_DEBT, debt_id)
        stmt = select(DefaultBucketEntry).where(
            DefaultBucketEntry.entity_type == SOURCE_DEBT,
            DefaultBucketEntry.entity_id == debt_id,
        )
        all_items = list((await self.pg_session.execute(stmt)).scalars().all())
        total_open = sum((i.amount + i.fine_amount for i in items), Decimal("0"))
        return all_items, total_open

    async def settle_default(
        self,
        entry_id: UUID,
        *,
        split_lines: list[dict] | None = None,
        note: str | None = None,
    ):
        svc = DefaultBucketService(self.pg_session)
        entry = await svc.settle(entry_id, split_lines=split_lines, note=note)
        debt = await resolve_debt(self.pg_session, entry.entity_id)
        if debt is not None:
            await _check_completion(self.pg_session, debt)
        await self.pg_session.commit()
        return entry

    async def waive_default(self, entry_id: UUID, *, note: str | None = None):
        svc = DefaultBucketService(self.pg_session)
        entry = await svc.waive(entry_id, note=note)
        debt = await resolve_debt(self.pg_session, entry.entity_id)
        if debt is not None:
            await _check_completion(self.pg_session, debt)
        await self.pg_session.commit()
        return entry

    # ------------------------------------------------------------------
    # Scope views API (Phase 2)
    # ------------------------------------------------------------------

    async def list_scope_views(self, debt_id: UUID) -> list[DebtScopeView]:
        return list(
            (
                await self.pg_session.execute(
                    select(DebtScopeView).where(DebtScopeView.debt_id == debt_id)
                )
            ).scalars().all()
        )

    async def upsert_scope_views(
        self,
        debt_id: UUID,
        owner_user_id: UUID,
        views: list[dict],
    ) -> list[DebtScopeView]:
        debt = (
            await self.pg_session.execute(select(Debt).where(Debt.id == debt_id))
        ).scalar_one_or_none()
        if debt is None:
            raise ValueError("Debt not found")
        if debt.owner_user_id != owner_user_id:
            raise PermissionError("Only the debt owner may manage scope views")

        existing = {
            (v.scope_kind, v.family_id, v.user_id): v
            for v in await self.list_scope_views(debt_id)
        }
        primary = next((v for v in existing.values() if v.is_primary), None)
        kept_keys: set[tuple] = set()
        result: list[DebtScopeView] = []

        for raw in views:
            scope_kind = raw["scope_kind"]
            family_id = raw.get("family_id")
            user_id = raw.get("user_id")
            if scope_kind == "FAMILY":
                if family_id is None:
                    raise ValueError("family_id required for FAMILY scope view")
                link = (
                    await self.pg_session.execute(
                        select(UserFamilyLink).where(
                            UserFamilyLink.user_id == owner_user_id,
                            UserFamilyLink.family_id == family_id,
                        )
                    )
                ).scalar_one_or_none()
                if link is None:
                    # Allow accepted relationship families linked to the owner's families
                    from app.api.routes.family.model import FamilyRelationship
                    from app.api.routes.family_relationship.family_relationship_service import (
                        RELATIONSHIP_ACTIVE,
                    )

                    owner_family_ids = list(
                        (
                            await self.pg_session.execute(
                                select(UserFamilyLink.family_id).where(
                                    UserFamilyLink.user_id == owner_user_id
                                )
                            )
                        ).scalars().all()
                    )
                    if not owner_family_ids:
                        raise PermissionError(
                            f"Owner must be a member of family {family_id} "
                            "or have an accepted relationship with it"
                        )
                    from sqlalchemy import and_

                    rel = (
                        await self.pg_session.execute(
                            select(FamilyRelationship.id).where(
                                FamilyRelationship.status == RELATIONSHIP_ACTIVE,
                                or_(
                                    and_(
                                        FamilyRelationship.family_a_id.in_(owner_family_ids),
                                        FamilyRelationship.family_b_id == family_id,
                                    ),
                                    and_(
                                        FamilyRelationship.family_b_id.in_(owner_family_ids),
                                        FamilyRelationship.family_a_id == family_id,
                                    ),
                                ),
                            )
                        )
                    ).scalar_one_or_none()
                    if rel is None:
                        raise PermissionError(
                            f"Owner must be a member of family {family_id} "
                            "or have an accepted relationship with it"
                        )
                user_id = None
            elif scope_kind == "PERSONAL":
                family_id = None
                user_id = user_id or owner_user_id
                allowed_family_ids = await self._allowed_funding_family_ids(owner_user_id)
                await self._validate_personal_payer(
                    owner_user_id, user_id, allowed_family_ids
                )
            else:
                raise ValueError(f"Invalid scope_kind: {scope_kind}")

            key = (scope_kind, family_id, user_id)
            kept_keys.add(key)
            is_masked = bool(raw.get("is_masked", False))
            show_breakdown = bool(raw.get("show_breakdown", False))
            # Owner's personal view always sees the full loan; other personal payers may be masked.
            if scope_kind == "PERSONAL" and user_id == owner_user_id:
                is_masked = False
                show_breakdown = True

            display_name = raw.get("display_name") or debt.debt_name
            payload = dict(
                display_name=display_name,
                display_type=raw.get("display_type") or debt.type,
                display_total_amount=raw.get("display_total_amount"),
                display_remaining_amount=raw.get("display_remaining_amount"),
                display_emi_amount=raw.get("display_emi_amount"),
                display_interest_rate=raw.get("display_interest_rate"),
                is_masked=is_masked,
                show_breakdown=show_breakdown,
                access_level=raw.get("access_level")
                or ("PRIVATE" if scope_kind == "PERSONAL" else "FAMILY"),
            )
            if not is_masked:
                payload["display_total_amount"] = (
                    payload["display_total_amount"] or debt.total_amount
                )
                payload["display_remaining_amount"] = (
                    payload["display_remaining_amount"] or debt.remaining_amount
                )
                payload["display_emi_amount"] = (
                    payload["display_emi_amount"]
                    if payload["display_emi_amount"] is not None
                    else debt.emi_amount
                )
                payload["display_interest_rate"] = (
                    payload["display_interest_rate"]
                    if payload["display_interest_rate"] is not None
                    else debt.interest_rate
                )

            if key in existing:
                view = existing[key]
                for k, v in payload.items():
                    setattr(view, k, v)
                result.append(view)
            else:
                view = DebtScopeView(
                    debt_id=debt_id,
                    scope_kind=scope_kind,
                    family_id=family_id,
                    user_id=user_id,
                    is_primary=False,
                    **payload,
                )
                self.pg_session.add(view)
                result.append(view)

        # Remove non-primary views not in the new set (never delete primary)
        for key, view in existing.items():
            if view.is_primary:
                continue
            if key not in kept_keys:
                await self.pg_session.delete(view)

        # Ensure primary still exists / updated if provided
        if primary and (primary.scope_kind, primary.family_id, primary.user_id) not in kept_keys:
            # Primary was omitted — keep it untouched
            result.append(primary)

        await self.pg_session.commit()
        return await self.list_scope_views(debt_id)

    async def list_payment_events(self, debt_id: UUID) -> list[DebtPaymentEvent]:
        events = list(
            (
                await self.pg_session.execute(
                    select(DebtPaymentEvent)
                    .where(DebtPaymentEvent.debt_id == debt_id)
                    .order_by(DebtPaymentEvent.paid_at.desc())
                )
            ).scalars().all()
        )
        if not events:
            return []
        event_ids = [e.id for e in events]
        allocs = list(
            (
                await self.pg_session.execute(
                    select(DebtPaymentAllocation).where(
                        DebtPaymentAllocation.payment_event_id.in_(event_ids)
                    )
                )
            ).scalars().all()
        )
        by_event: dict[UUID, list[DebtPaymentAllocation]] = {eid: [] for eid in event_ids}
        for a in allocs:
            by_event.setdefault(a.payment_event_id, []).append(a)
        for e in events:
            setattr(e, "_allocations", by_event.get(e.id, []))
        return events

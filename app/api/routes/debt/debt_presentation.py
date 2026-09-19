"""Debt presentation helpers — map canonical debt + scope view to API rows."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from app.api.routes.debt.model import Debt, DebtScopeView


@dataclass
class DebtRow:
    """API-compatible debt row built from canonical Debt + optional scope view."""

    id: UUID
    family_id: UUID
    scope_type: str
    debt_name: str
    type: str
    status: str
    debt_in_the_name_of: UUID
    user_id: UUID
    is_personal: bool

    total_amount: Decimal
    remaining_amount: Decimal
    total_paid: Decimal

    has_interest: bool
    interest_type: Optional[str]
    interest_rate: Optional[float]
    compounding_frequency: Optional[str]
    fixed_fee_amount: Optional[Decimal]
    interest_increase_every: Optional[str]
    interest_increase_percentage: Optional[float]
    next_interest_increase_date: Optional[datetime]

    has_emi: bool
    emi_amount: Optional[Decimal]
    emi_every: Optional[str]
    emi_interval_days: Optional[int] = None
    emi_interval_months: Optional[int] = None
    emi_interval_years: Optional[int] = None
    tenure_months: Optional[int] = None
    emi_next_date: Optional[datetime] = None
    requires_confirmation: bool = True

    bounce_fine_amount: Decimal = Decimal("0")
    allow_auto_default: bool = True

    is_masked: bool = False
    show_split_to_family: bool = False
    real_total_amount: Optional[Decimal] = None
    real_remaining_amount: Optional[Decimal] = None
    real_emi_amount: Optional[Decimal] = None
    real_interest_rate: Optional[float] = None

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    document_id: Optional[UUID] = None
    access_level: str = "FAMILY"
    show_doc_to_all: bool = True
    doc_viewer_user_ids: Optional[list[UUID]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    view_id: Optional[UUID] = None
    show_breakdown: bool = False
    scope_views: list[dict[str, Any]] = field(default_factory=list)
    balance_for_part_payment: Decimal = Decimal("0")
    split_lines: list[dict[str, Any]] = field(default_factory=list)
    my_emi_amount: Optional[Decimal] = None
    my_obligation_remaining: Optional[Decimal] = None
    my_expected_total: Optional[Decimal] = None
    can_contribute: bool = False
    is_owner: bool = False
    can_part_payment: bool = False

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family_id": self.family_id,
            "scope_type": self.scope_type,
            "debt_name": self.debt_name,
            "type": self.type,
            "status": self.status,
            "debt_in_the_name_of": self.debt_in_the_name_of,
            "user_id": self.user_id,
            "is_personal": self.is_personal,
            "total_amount": self.total_amount,
            "remaining_amount": self.remaining_amount,
            "total_paid": self.total_paid,
            "balance_for_part_payment": self.balance_for_part_payment,
            "has_interest": self.has_interest,
            "interest_type": self.interest_type,
            "interest_rate": self.interest_rate,
            "compounding_frequency": self.compounding_frequency,
            "fixed_fee_amount": self.fixed_fee_amount,
            "interest_increase_every": self.interest_increase_every,
            "interest_increase_percentage": self.interest_increase_percentage,
            "next_interest_increase_date": self.next_interest_increase_date,
            "has_emi": self.has_emi,
            "emi_amount": self.emi_amount,
            "emi_every": self.emi_every,
            "emi_interval_days": self.emi_interval_days,
            "emi_interval_months": self.emi_interval_months,
            "emi_interval_years": self.emi_interval_years,
            "tenure_months": self.tenure_months,
            "emi_next_date": self.emi_next_date,
            "requires_confirmation": self.requires_confirmation,
            "bounce_fine_amount": self.bounce_fine_amount,
            "allow_auto_default": self.allow_auto_default,
            "is_masked": self.is_masked,
            "show_split_to_family": self.show_split_to_family,
            "real_total_amount": self.real_total_amount,
            "real_remaining_amount": self.real_remaining_amount,
            "real_emi_amount": self.real_emi_amount,
            "real_interest_rate": self.real_interest_rate,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "completed_at": self.completed_at,
            "document_id": self.document_id,
            "access_level": self.access_level,
            "show_doc_to_all": self.show_doc_to_all,
            "doc_viewer_user_ids": self.doc_viewer_user_ids,
            "created_at": self.created_at,
            "view_id": self.view_id,
            "show_breakdown": self.show_breakdown,
            "scope_views": self.scope_views,
            "split_lines": self.split_lines,
            "my_emi_amount": self.my_emi_amount,
            "my_obligation_remaining": self.my_obligation_remaining,
            "my_expected_total": self.my_expected_total,
            "can_contribute": self.can_contribute,
            "is_owner": self.is_owner,
            "can_part_payment": self.can_part_payment,
        }


def build_debt_row(
    debt: Debt,
    view: DebtScopeView | None,
    *,
    viewer_user_id: UUID | None = None,
    include_real: bool | None = None,
    all_views: list[DebtScopeView] | None = None,
    split_lines: list[dict[str, Any]] | None = None,
) -> DebtRow:
    is_personal = bool(view and view.scope_kind == "PERSONAL")
    family_id = (
        (view.family_id if view and view.family_id else None)
        or debt.primary_family_id
        or UUID(int=0)
    )
    owner = debt.owner_user_id
    is_owner = viewer_user_id is not None and viewer_user_id == owner
    # Masked personal shares (other members) and masked family views both use share-only fields.
    masked = bool(view and view.is_masked and not is_owner)
    show_breakdown = bool(view.show_breakdown) if view else False
    # Document: always owner; optionally also scopes with Full details when show_doc_to_all.
    share_doc_with_full_details = bool(getattr(debt, "show_doc_to_all", False))
    can_see_doc = bool(
        is_owner
        or (share_doc_with_full_details and view and view.show_breakdown)
    )

    lines = split_lines or []
    my_line: dict[str, Any] | None = None
    if viewer_user_id and lines:
        for ln in lines:
            if ln.get("poolType") == "PERSONAL" and str(ln.get("userId") or "") == str(
                viewer_user_id
            ):
                my_line = ln
                break
        if my_line is None and view and view.scope_kind == "FAMILY" and view.family_id:
            for ln in lines:
                if ln.get("poolType") in ("CURRENT_FAMILY", "OTHER_FAMILY") and str(
                    ln.get("familyId") or ""
                ) == str(view.family_id):
                    my_line = ln
                    break

    my_emi = Decimal(str(my_line["amount"])) if my_line and my_line.get("amount") is not None else None
    my_expected = (
        Decimal(str(my_line["expectedTotal"]))
        if my_line and my_line.get("expectedTotal") is not None
        else None
    )
    my_obligation = (
        Decimal(str(my_line["obligationRemaining"]))
        if my_line and my_line.get("obligationRemaining") is not None
        else None
    )
    can_contribute = bool(my_line) and debt.status == "ACTIVE"

    # Public/display fields for non-owners on masked views: only their EMI + obligation.
    if masked and not show_breakdown:
        total = my_expected if my_expected is not None else (
            view.display_total_amount if view and view.display_total_amount is not None else debt.total_amount
        )
        remaining = my_obligation if my_obligation is not None else (
            view.display_remaining_amount
            if view and view.display_remaining_amount is not None
            else debt.remaining_amount
        )
        emi = my_emi if my_emi is not None else (
            view.display_emi_amount if view and view.display_emi_amount is not None else debt.emi_amount
        )
        rate = None
        name = view.display_name if view else debt.debt_name
        dtype = (view.display_type if view and view.display_type else None) or debt.type
    elif masked:
        # Full details: see real loan + own share fields on my_* 
        total = debt.total_amount
        remaining = debt.remaining_amount
        emi = debt.emi_amount
        rate = debt.interest_rate
        name = debt.debt_name
        dtype = debt.type
    else:
        total = debt.total_amount
        remaining = debt.remaining_amount
        emi = debt.emi_amount
        rate = debt.interest_rate
        name = debt.debt_name
        dtype = debt.type

    show_real = include_real if include_real is not None else (bool(view and view.is_masked) and is_owner)

    scope_views_payload: list[dict[str, Any]] = []
    if all_views and is_owner:
        for v in all_views:
            scope_views_payload.append(
                {
                    "id": str(v.id),
                    "scopeKind": v.scope_kind,
                    "familyId": str(v.family_id) if v.family_id else None,
                    "userId": str(v.user_id) if v.user_id else None,
                    "isPrimary": v.is_primary,
                    "displayName": v.display_name,
                    "displayType": v.display_type,
                    "displayTotalAmount": v.display_total_amount,
                    "displayRemainingAmount": v.display_remaining_amount,
                    "displayEmiAmount": v.display_emi_amount,
                    "displayInterestRate": v.display_interest_rate,
                    "isMasked": v.is_masked,
                    "showBreakdown": v.show_breakdown,
                    "accessLevel": v.access_level,
                }
            )

    # Owners get full split lines; non-owners get only their own line (if any).
    lines_out: list[dict[str, Any]] = []
    if is_owner:
        lines_out = lines
    elif my_line:
        lines_out = [my_line]

    balance = getattr(debt, "balance_for_part_payment", None) or Decimal("0")
    if not is_owner:
        # Non-owners can see balance only if they are a payer (so they know pool status).
        balance = balance if can_contribute or show_breakdown else Decimal("0")

    return DebtRow(
        id=debt.id,
        family_id=family_id,
        scope_type="PERSONAL" if is_personal else "FAMILY",
        debt_name=name,
        type=dtype,
        status=debt.status,
        debt_in_the_name_of=owner,
        user_id=owner,
        is_personal=is_personal,
        total_amount=total,
        remaining_amount=remaining,
        total_paid=debt.total_paid if (is_owner or show_breakdown) else Decimal("0"),
        has_interest=debt.has_interest if (is_owner or show_breakdown) else False,
        interest_type=debt.interest_type if (is_owner or show_breakdown) else None,
        interest_rate=rate,
        compounding_frequency=debt.compounding_frequency if (is_owner or show_breakdown) else None,
        fixed_fee_amount=debt.fixed_fee_amount if (is_owner or show_breakdown) else None,
        interest_increase_every=debt.interest_increase_every if (is_owner or show_breakdown) else None,
        interest_increase_percentage=(
            debt.interest_increase_percentage if (is_owner or show_breakdown) else None
        ),
        next_interest_increase_date=(
            debt.next_interest_increase_date if (is_owner or show_breakdown) else None
        ),
        has_emi=debt.has_emi,
        emi_amount=emi,
        emi_every=debt.emi_every,
        emi_interval_days=getattr(debt, "emi_interval_days", None),
        emi_interval_months=getattr(debt, "emi_interval_months", None),
        emi_interval_years=getattr(debt, "emi_interval_years", None),
        tenure_months=debt.tenure_months if (is_owner or show_breakdown) else None,
        emi_next_date=debt.emi_next_date,
        requires_confirmation=debt.requires_confirmation,
        bounce_fine_amount=debt.bounce_fine_amount if is_owner else Decimal("0"),
        allow_auto_default=debt.allow_auto_default,
        is_masked=bool(view and view.is_masked),
        show_split_to_family=bool(view.show_breakdown) if view else False,
        real_total_amount=debt.total_amount if show_real else None,
        real_remaining_amount=debt.remaining_amount if show_real else None,
        real_emi_amount=debt.emi_amount if show_real else None,
        real_interest_rate=debt.interest_rate if show_real else None,
        start_date=debt.start_date if (is_owner or show_breakdown) else None,
        end_date=debt.end_date if (is_owner or show_breakdown) else None,
        completed_at=debt.completed_at,
        document_id=debt.document_id if can_see_doc else None,
        access_level=view.access_level if view else ("PRIVATE" if is_personal else "FAMILY"),
        show_doc_to_all=share_doc_with_full_details if can_see_doc else False,
        doc_viewer_user_ids=(
            getattr(debt, "doc_viewer_user_ids", None) if can_see_doc else None
        ),
        created_at=debt.created_at,
        view_id=view.id if view else None,
        show_breakdown=show_breakdown,
        scope_views=scope_views_payload,
        balance_for_part_payment=balance,
        split_lines=lines_out,
        my_emi_amount=my_emi,
        my_obligation_remaining=my_obligation,
        my_expected_total=my_expected,
        can_contribute=can_contribute,
        is_owner=is_owner,
        can_part_payment=bool(is_owner and debt.status == "ACTIVE"),
    )

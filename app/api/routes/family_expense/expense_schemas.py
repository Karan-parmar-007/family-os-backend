from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from typing import Annotated, List, Optional, Self
from uuid import UUID

from fastapi import Form
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.api.schemas.pagination import PaginatedResponse
from app.api.schemas.funding import FundingSourceInput
from app.core.funding_sources import validate_family_personal_log_split


def _empty_str_to_none(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value


def _parse_optional_datetime(value: str | None) -> datetime | None:
    cleaned = _empty_str_to_none(value)
    if cleaned is None:
        return None
    return datetime.fromisoformat(cleaned)


def _parse_optional_decimal(value: str | None) -> Decimal | None:
    cleaned = _empty_str_to_none(value)
    if cleaned is None:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal value") from exc


def _parse_optional_uuid(value: str | None) -> UUID | None:
    cleaned = _empty_str_to_none(value)
    if cleaned is None:
        return None
    try:
        return UUID(cleaned)
    except ValueError as exc:
        raise ValueError("Invalid UUID value") from exc


def _parse_optional_int(value: str | None) -> int | None:
    cleaned = _empty_str_to_none(value)
    if cleaned is None:
        return None
    try:
        return int(cleaned)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid integer value") from exc


def _parse_optional_bool(value: str | bool | None) -> bool:
    """Parse an optional bool from form data (accepts 'true'/'false' strings)."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return value.strip().lower() in ("true", "1", "yes")


def _parse_uuid_list(value: str | None) -> list[UUID]:
    """Parse a comma-separated string of UUIDs into a list."""
    cleaned = _empty_str_to_none(value)
    if cleaned is None:
        return []
    result = []
    errors = []
    for raw in cleaned.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            result.append(UUID(raw))
        except ValueError:
            errors.append(f"Invalid UUID: {raw!r}")
    if errors:
        raise ValueError("; ".join(errors))
    return result


def _parse_funding_sources(value: str | None) -> list[FundingSourceInput] | None:
    cleaned = _empty_str_to_none(value)
    if cleaned is None:
        return None
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON for funding_sources") from exc
    if not isinstance(raw, list):
        raise ValueError("funding_sources must be a JSON array")
    return [FundingSourceInput.model_validate(item) for item in raw]


def _parse_family_splits(value: str | None) -> list["FamilySplitInput"]:
    cleaned = _empty_str_to_none(value)
    if cleaned is None:
        return []
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON for family_splits") from exc
    if not isinstance(raw, list):
        raise ValueError("family_splits must be a JSON array")
    return [FamilySplitInput.model_validate(item) for item in raw]


def _parse_personal_splits(value: str | None) -> list["PersonalSplitInput"]:
    cleaned = _empty_str_to_none(value)
    if cleaned is None:
        return []
    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON for personal_splits") from exc
    if not isinstance(raw, list):
        raise ValueError("personal_splits must be a JSON array")
    return [PersonalSplitInput.model_validate(item) for item in raw]


def _validate_expense_splits(
    total_amount: Decimal,
    personal_savings_amount: Decimal | None,
    family_splits: list["FamilySplitInput"],
) -> None:
    if total_amount <= 0:
        raise ValueError("total_amount must be greater than 0")

    personal = personal_savings_amount or Decimal("0")
    if personal < 0:
        raise ValueError("personal_savings_amount cannot be negative")

    seen_families: set[UUID] = set()
    split_sum = Decimal("0")
    for split in family_splits:
        if split.amount <= 0:
            raise ValueError(f"Split for family {split.family_id} must be greater than zero")
        if split.family_id in seen_families:
            raise ValueError("Each family can only be selected once")
        seen_families.add(split.family_id)
        split_sum += split.amount

    if personal + split_sum != total_amount:
        raise ValueError(
            f"Splits ({personal + split_sum}) must add up to the total amount ({total_amount})"
        )
    if personal + split_sum == 0:
        raise ValueError("Allocate the total amount to personal savings and/or at least one family")


def _validate_expense_recurrence(
    paid_every: str | None,
    repeat_interval_days: int | None,
    repeat_interval_months: int | None,
    repeat_interval_years: int | None,
) -> None:
    """Require either a preset frequency or at least one custom interval (any combination)."""
    custom_intervals = (
        repeat_interval_days,
        repeat_interval_months,
        repeat_interval_years,
    )
    custom_count = sum(interval is not None for interval in custom_intervals)

    if paid_every:
        if custom_count > 0:
            raise ValueError(
                "Choose either a preset frequency or a custom interval, not both"
            )
        return

    if custom_count == 0:
        raise ValueError("Select how often this expense repeats")


# ---------------------------------------------------------------------------
# Recurring expense — Create / update
# ---------------------------------------------------------------------------

class FamilySplitInput(BaseModel):
    family_id: UUID
    split_name: str = Field(..., min_length=1, max_length=255)
    amount: Decimal = Field(..., gt=0)


class PersonalSplitInput(BaseModel):
    user_id: UUID
    amount: Decimal = Field(..., gt=0)


class RecurringExpenseCreateRequest(BaseModel):
    expense_name: str = Field(..., min_length=1, max_length=255)
    total_amount: Decimal = Field(..., gt=0)
    personal_savings_amount: Decimal | None = Field(default=None, ge=0)
    family_splits: list[FamilySplitInput] = Field(default_factory=list)
    personal_splits: list[PersonalSplitInput] = Field(default_factory=list)

    paid_every: str | None = None
    repeat_interval_days: int | None = Field(default=None, ge=1)
    repeat_interval_months: int | None = Field(default=None, ge=1)
    repeat_interval_years: int | None = Field(default=None, ge=1)
    next_payment_date: datetime | None = None

    show_docs_to_all: bool = Field(default=False)
    repeat_doc_with_logs: bool = Field(default=False)
    doc_viewer_user_ids: list[UUID] = Field(default_factory=list)
    let_everyone_edit: bool = Field(default=False)
    category_id: UUID | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        if self.personal_splits:
            self.personal_savings_amount = sum(
                (s.amount for s in self.personal_splits), Decimal("0")
            )
        _validate_expense_splits(
            self.total_amount, self.personal_savings_amount, self.family_splits
        )
        _validate_expense_recurrence(
            self.paid_every,
            self.repeat_interval_days,
            self.repeat_interval_months,
            self.repeat_interval_years,
        )
        if self.next_payment_date is None:
            raise ValueError("next_payment_date is required")
        return self

    @classmethod
    def as_form(
        cls,
        expense_name: Annotated[str, Form(min_length=1, max_length=255)],
        total_amount: Annotated[Decimal, Form(gt=0)],
        family_splits: Annotated[str | None, Form()] = None,
        personal_splits: Annotated[str | None, Form()] = None,
        paid_every: Annotated[str | None, Form()] = None,
        repeat_interval_days: Annotated[str | None, Form()] = None,
        repeat_interval_months: Annotated[str | None, Form()] = None,
        repeat_interval_years: Annotated[str | None, Form()] = None,
        next_payment_date: Annotated[str | None, Form()] = None,
        personal_savings_amount: Annotated[str | None, Form()] = None,
        show_docs_to_all: Annotated[str | None, Form()] = None,
        repeat_doc_with_logs: Annotated[str | None, Form()] = None,
        doc_viewer_user_ids: Annotated[str | None, Form()] = None,
        category_id: Annotated[str | None, Form()] = None,
    ) -> Self:
        return cls(
            expense_name=expense_name,
            total_amount=total_amount,
            family_splits=_parse_family_splits(family_splits),
            personal_splits=_parse_personal_splits(personal_splits),
            paid_every=_empty_str_to_none(paid_every),
            repeat_interval_days=_parse_optional_int(repeat_interval_days),
            repeat_interval_months=_parse_optional_int(repeat_interval_months),
            repeat_interval_years=_parse_optional_int(repeat_interval_years),
            next_payment_date=_parse_optional_datetime(next_payment_date),
            personal_savings_amount=_parse_optional_decimal(personal_savings_amount),
            show_docs_to_all=_parse_optional_bool(show_docs_to_all),
            repeat_doc_with_logs=_parse_optional_bool(repeat_doc_with_logs),
            doc_viewer_user_ids=_parse_uuid_list(doc_viewer_user_ids),
            category_id=_parse_optional_uuid(category_id),
        )


class RecurringExpenseQuickAddRequest(BaseModel):
    """Family-page quick add: this family + optional personal (multi-person allowed)."""

    expense_name: str = Field(..., min_length=1, max_length=255)
    total_amount: Decimal = Field(..., gt=0)
    family_amount: Decimal | None = Field(default=None, ge=0)
    personal_savings_amount: Decimal | None = Field(default=None, ge=0)
    personal_splits: list[PersonalSplitInput] = Field(default_factory=list)
    split_name: str | None = Field(default=None, max_length=255)

    paid_every: str | None = None
    repeat_interval_days: int | None = Field(default=None, ge=1)
    repeat_interval_months: int | None = Field(default=None, ge=1)
    repeat_interval_years: int | None = Field(default=None, ge=1)
    next_payment_date: datetime | None = None

    show_docs_to_all: bool = Field(default=False)
    repeat_doc_with_logs: bool = Field(default=False)
    doc_viewer_user_ids: list[UUID] = Field(default_factory=list)
    let_everyone_edit: bool = Field(default=False)
    category_id: UUID | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        family = self.family_amount
        personal = self.personal_savings_amount

        if self.personal_splits:
            seen: set[UUID] = set()
            personal = Decimal("0")
            for split in self.personal_splits:
                if split.amount <= 0:
                    raise ValueError("Each personal split must be greater than zero")
                if split.user_id in seen:
                    raise ValueError("Each person can only be selected once in personal splits")
                seen.add(split.user_id)
                personal += split.amount
            if family is None:
                family = self.total_amount - personal
            if family < 0 or family + personal != self.total_amount:
                raise ValueError(
                    f"Family ({family}) and personal ({personal}) must add up to total ({self.total_amount})"
                )
            self.family_amount = family
            self.personal_savings_amount = personal if personal > 0 else None
        elif family is None and personal is None:
            # No split — entire amount goes to this family (quick-add default).
            pass
        else:
            fa = family or Decimal("0")
            pa = personal or Decimal("0")
            if fa <= 0 or pa <= 0:
                raise ValueError(
                    "When splitting expense, both family and personal amounts must be greater than zero."
                )
            if fa + pa != self.total_amount:
                raise ValueError(
                    f"Family ({fa}) and personal ({pa}) must add up to total ({self.total_amount})"
                )
        _validate_expense_recurrence(
            self.paid_every,
            self.repeat_interval_days,
            self.repeat_interval_months,
            self.repeat_interval_years,
        )
        if self.next_payment_date is None:
            raise ValueError("next_payment_date is required")
        return self

    @classmethod
    def as_form(
        cls,
        expense_name: Annotated[str, Form(min_length=1, max_length=255)],
        total_amount: Annotated[Decimal, Form(gt=0)],
        family_amount: Annotated[str | None, Form()] = None,
        personal_savings_amount: Annotated[str | None, Form()] = None,
        personal_splits: Annotated[str | None, Form()] = None,
        split_name: Annotated[str | None, Form()] = None,
        paid_every: Annotated[str | None, Form()] = None,
        repeat_interval_days: Annotated[str | None, Form()] = None,
        repeat_interval_months: Annotated[str | None, Form()] = None,
        repeat_interval_years: Annotated[str | None, Form()] = None,
        next_payment_date: Annotated[str | None, Form()] = None,
        show_docs_to_all: Annotated[str | None, Form()] = None,
        repeat_doc_with_logs: Annotated[str | None, Form()] = None,
        doc_viewer_user_ids: Annotated[str | None, Form()] = None,
        let_everyone_edit: Annotated[str | None, Form()] = None,
        category_id: Annotated[str | None, Form()] = None,
    ) -> Self:
        return cls(
            expense_name=expense_name,
            total_amount=total_amount,
            family_amount=_parse_optional_decimal(family_amount),
            personal_savings_amount=_parse_optional_decimal(personal_savings_amount),
            personal_splits=_parse_personal_splits(personal_splits),
            split_name=_empty_str_to_none(split_name),
            paid_every=_empty_str_to_none(paid_every),
            repeat_interval_days=_parse_optional_int(repeat_interval_days),
            repeat_interval_months=_parse_optional_int(repeat_interval_months),
            repeat_interval_years=_parse_optional_int(repeat_interval_years),
            next_payment_date=_parse_optional_datetime(next_payment_date),
            show_docs_to_all=_parse_optional_bool(show_docs_to_all),
            repeat_doc_with_logs=_parse_optional_bool(repeat_doc_with_logs),
            doc_viewer_user_ids=_parse_uuid_list(doc_viewer_user_ids),
            let_everyone_edit=_parse_optional_bool(let_everyone_edit) or False,
            category_id=_parse_optional_uuid(category_id),
        )


class RecurringExpenseUpdateRequest(BaseModel):
    expense_name: str | None = Field(default=None, min_length=1, max_length=255)
    total_amount: Decimal | None = Field(default=None, gt=0)
    personal_savings_amount: Decimal | None = Field(default=None, ge=0)
    family_splits: list[FamilySplitInput] | None = None
    personal_splits: list[PersonalSplitInput] | None = None

    paid_every: str | None = None
    repeat_interval_days: int | None = Field(default=None, ge=1)
    repeat_interval_months: int | None = Field(default=None, ge=1)
    repeat_interval_years: int | None = Field(default=None, ge=1)
    next_payment_date: datetime | None = None

    show_docs_to_all: bool | None = None
    repeat_doc_with_logs: bool | None = None
    doc_viewer_user_ids: list[UUID] | None = None
    let_everyone_edit: bool | None = None
    category_id: UUID | None = None

    @classmethod
    def as_form(
        cls,
        expense_name: Annotated[str | None, Form(min_length=1, max_length=255)] = None,
        total_amount: Annotated[str | None, Form()] = None,
        family_splits: Annotated[str | None, Form()] = None,
        personal_splits: Annotated[str | None, Form()] = None,
        paid_every: Annotated[str | None, Form()] = None,
        repeat_interval_days: Annotated[str | None, Form()] = None,
        repeat_interval_months: Annotated[str | None, Form()] = None,
        repeat_interval_years: Annotated[str | None, Form()] = None,
        next_payment_date: Annotated[str | None, Form()] = None,
        personal_savings_amount: Annotated[str | None, Form()] = None,
        show_docs_to_all: Annotated[str | None, Form()] = None,
        repeat_doc_with_logs: Annotated[str | None, Form()] = None,
        doc_viewer_user_ids: Annotated[str | None, Form()] = None,
        let_everyone_edit: Annotated[str | None, Form()] = None,
        category_id: Annotated[str | None, Form()] = None,
    ) -> Self:
        parsed_splits: list[FamilySplitInput] | None = None
        if family_splits is not None:
            parsed_splits = _parse_family_splits(family_splits)
        parsed_personal: list[PersonalSplitInput] | None = None
        if personal_splits is not None:
            parsed_personal = _parse_personal_splits(personal_splits)
        parsed_doc_viewers: list[UUID] | None = None
        if doc_viewer_user_ids is not None:
            parsed_doc_viewers = _parse_uuid_list(doc_viewer_user_ids)
        return cls(
            expense_name=_empty_str_to_none(expense_name),
            total_amount=_parse_optional_decimal(total_amount),
            family_splits=parsed_splits,
            personal_splits=parsed_personal,
            paid_every=_empty_str_to_none(paid_every),
            repeat_interval_days=_parse_optional_int(repeat_interval_days),
            repeat_interval_months=_parse_optional_int(repeat_interval_months),
            repeat_interval_years=_parse_optional_int(repeat_interval_years),
            next_payment_date=_parse_optional_datetime(next_payment_date),
            personal_savings_amount=_parse_optional_decimal(personal_savings_amount),
            show_docs_to_all=_parse_optional_bool(show_docs_to_all) if show_docs_to_all is not None else None,
            repeat_doc_with_logs=_parse_optional_bool(repeat_doc_with_logs) if repeat_doc_with_logs is not None else None,
            doc_viewer_user_ids=parsed_doc_viewers,
            let_everyone_edit=_parse_optional_bool(let_everyone_edit) if let_everyone_edit is not None else None,
            category_id=_parse_optional_uuid(category_id),
        )


# Backward-compatible aliases
FamilyRecurringExpenseCreateRequest = RecurringExpenseCreateRequest
FamilyRecurringExpenseUpdateRequest = RecurringExpenseUpdateRequest


# ---------------------------------------------------------------------------
# Recurring expense — Response shapes
# ---------------------------------------------------------------------------

class FamilyRecurringExpenseSplitSummary(BaseModel):
    """Read-only family view of one recurring expense split."""

    id: UUID
    recurring_expense_id: UUID
    split_name: str
    amount: Decimal
    paid_every: str | None = None
    repeat_interval_days: int | None = None
    repeat_interval_months: int | None = None
    repeat_interval_years: int | None = None
    next_payment_date: datetime | None = None
    paid_by_user_id: UUID


class FamilyRecurringExpenseSummary(FamilyRecurringExpenseSplitSummary):
    """Alias for family list responses."""

    @computed_field
    @property
    def display_amount(self) -> Decimal:
        return self.amount


class RecurringExpenseFamilySplitDetail(BaseModel):
    family_id: UUID
    family_name: str | None = None
    split_name: str
    amount: Decimal


class RecurringExpensePersonalSplitDetail(BaseModel):
    user_id: UUID
    amount: Decimal


class RecurringExpenseDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    expense_name: str
    total_amount: Decimal
    personal_savings_amount: Decimal | None = None
    paid_every: str | None = None
    repeat_interval_days: int | None = None
    repeat_interval_months: int | None = None
    repeat_interval_years: int | None = None
    next_payment_date: datetime | None = None
    document_id: UUID | None = None
    show_docs_to_all: bool = False
    repeat_doc_with_logs: bool = False
    is_family_managed: bool = False
    let_everyone_edit: bool = False
    doc_viewer_user_ids: list[UUID] = Field(default_factory=list)
    family_splits: list[RecurringExpenseFamilySplitDetail] = Field(default_factory=list)
    personal_splits: list[RecurringExpensePersonalSplitDetail] = Field(default_factory=list)
    can_edit: bool | None = None
    category_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


FamilyRecurringExpenseDetail = RecurringExpenseDetail


# ---------------------------------------------------------------------------
# Expense log — Create
# ---------------------------------------------------------------------------

class FamilyExpenseLogCreateRequest(BaseModel):
    """Validated form fields for creating a family expense log.

    family_amount and personal_savings_amount are optional — if omitted (and no
    funding_sources), the full total debits this family's savings. If provided,
    they must sum to total_amount.
    """

    expense_name: str = Field(..., min_length=1, max_length=255)
    total_amount: Decimal = Field(..., gt=0)
    expense_date: datetime = Field(...)

    # Optional split
    family_amount: Decimal | None = Field(default=None, ge=0)
    personal_savings_amount: Decimal | None = Field(default=None, ge=0)
    personal_savings_user_id: UUID | None = None
    funding_sources: list[FundingSourceInput] | None = None

    scope_type: str = Field(default="FAMILY")

    document_id: UUID | None = None
    show_doc_to_all: bool = Field(default=False)

    # Granular per-user doc access (only used when show_doc_to_all=False)
    doc_viewer_user_ids: list[UUID] = Field(default_factory=list)
    let_everyone_edit: bool = Field(default=False)
    show_funding_to_family: bool = Field(default=False)

    category_id: UUID | None = None
    expense_made_for_user_id: UUID | None = None
    logged_by: UUID | None = None

    @model_validator(mode="after")
    def validate_amounts(self) -> Self:
        errors = []

        family_amount = self.family_amount
        personal_amount = self.personal_savings_amount

        # If the new split format is used, legacy split fields are optional.
        if self.funding_sources is not None:
            split_total = sum((item.amount for item in self.funding_sources), Decimal("0"))
            if split_total != self.total_amount:
                errors.append(
                    f"funding_sources total ({split_total}) must equal total_amount ({self.total_amount})"
                )
            if errors:
                raise ValueError("; ".join(errors))
            return self

        # If neither legacy split is provided, that's fine — no further validation needed
        if family_amount is None and personal_amount is None:
            return self

        try:
            validate_family_personal_log_split(
                self.total_amount, family_amount, personal_amount
            )
        except ValueError as exc:
            errors.append(str(exc))

        if personal_amount and personal_amount > 0 and not self.personal_savings_user_id:
            errors.append("personal_savings_user_id is required when personal_savings_amount is set")

        if errors:
            raise ValueError("; ".join(errors))

        return self

    @classmethod
    def as_form(
        cls,
        expense_name: Annotated[str, Form(min_length=1, max_length=255)],
        total_amount: Annotated[Decimal, Form(gt=0)],
        expense_date: Annotated[str, Form()],
        family_amount: Annotated[str | None, Form()] = None,
        personal_savings_amount: Annotated[str | None, Form()] = None,
        personal_savings_user_id: Annotated[str | None, Form()] = None,
        funding_sources: Annotated[str | None, Form()] = None,
        document_id: Annotated[str | None, Form()] = None,
        show_doc_to_all: Annotated[str | None, Form()] = None,
        doc_viewer_user_ids: Annotated[str | None, Form()] = None,
        let_everyone_edit: Annotated[str | None, Form()] = None,
        show_funding_to_family: Annotated[str | None, Form()] = None,
        category_id: Annotated[str | None, Form()] = None,
        expense_made_for_user_id: Annotated[str | None, Form()] = None,
        logged_by: Annotated[str | None, Form()] = None,
    ) -> Self:
        return cls(
            expense_name=expense_name,
            total_amount=total_amount,
            expense_date=_parse_optional_datetime(expense_date) or datetime.now(timezone.utc),
            family_amount=_parse_optional_decimal(family_amount),
            personal_savings_amount=_parse_optional_decimal(personal_savings_amount),
            personal_savings_user_id=_parse_optional_uuid(personal_savings_user_id),
            funding_sources=_parse_funding_sources(funding_sources),
            document_id=_parse_optional_uuid(document_id),
            show_doc_to_all=_parse_optional_bool(show_doc_to_all),
            doc_viewer_user_ids=_parse_uuid_list(doc_viewer_user_ids),
            let_everyone_edit=_parse_optional_bool(let_everyone_edit) or False,
            show_funding_to_family=_parse_optional_bool(show_funding_to_family) or False,
            category_id=_parse_optional_uuid(category_id),
            expense_made_for_user_id=_parse_optional_uuid(expense_made_for_user_id),
            logged_by=_parse_optional_uuid(logged_by),
        )


# ---------------------------------------------------------------------------
# Expense log — Update
# ---------------------------------------------------------------------------

class FamilyExpenseLogUpdateRequest(BaseModel):
    """Validated form fields for partially updating a family expense log.

    Only fields included in the multipart request are applied; omitted fields are left unchanged.
    family_amount / personal_savings_amount are optional; if sent they must sum to total_amount.
    """

    expense_name: str | None = Field(default=None, min_length=1, max_length=255)
    total_amount: Decimal | None = Field(default=None, gt=0)
    family_amount: Decimal | None = Field(default=None, ge=0)
    expense_date: datetime | None = None
    personal_savings_amount: Decimal | None = Field(default=None, ge=0)
    personal_savings_user_id: UUID | None = None
    funding_sources: list[FundingSourceInput] | None = None
    document_id: UUID | None = None
    show_doc_to_all: bool | None = None
    show_funding_to_family: bool | None = None

    # None = don't touch; empty list = remove all; populated list = replace access list
    doc_viewer_user_ids: list[UUID] | None = None

    category_id: UUID | None = None
    expense_made_for_user_id: UUID | None = None
    logged_by: UUID | None = None

    @field_validator("total_amount")
    @classmethod
    def validate_total_amount(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("total_amount must be greater than 0")
        return value

    @field_validator("family_amount")
    @classmethod
    def validate_family_amount(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("family_amount cannot be negative")
        return value

    @classmethod
    def as_form(
        cls,
        expense_name: Annotated[str | None, Form(min_length=1, max_length=255)] = None,
        total_amount: Annotated[str | None, Form()] = None,
        family_amount: Annotated[str | None, Form()] = None,
        expense_date: Annotated[str | None, Form()] = None,
        personal_savings_amount: Annotated[str | None, Form()] = None,
        personal_savings_user_id: Annotated[str | None, Form()] = None,
        document_id: Annotated[str | None, Form()] = None,
        show_doc_to_all: Annotated[str | None, Form()] = None,
        show_funding_to_family: Annotated[str | None, Form()] = None,
        doc_viewer_user_ids: Annotated[str | None, Form()] = None,
        funding_sources: Annotated[str | None, Form()] = None,
        category_id: Annotated[str | None, Form()] = None,
        expense_made_for_user_id: Annotated[str | None, Form()] = None,
        logged_by: Annotated[str | None, Form()] = None,
    ) -> Self:
        parsed_doc_viewers: list[UUID] | None = None
        if doc_viewer_user_ids is not None:
            parsed_doc_viewers = _parse_uuid_list(doc_viewer_user_ids)

        kwargs = {}
        if category_id is not None:
            kwargs["category_id"] = _parse_optional_uuid(category_id)
        if expense_made_for_user_id is not None:
            kwargs["expense_made_for_user_id"] = _parse_optional_uuid(expense_made_for_user_id)
        if logged_by is not None:
            kwargs["logged_by"] = _parse_optional_uuid(logged_by)

        return cls(
            expense_name=_empty_str_to_none(expense_name),
            total_amount=_parse_optional_decimal(total_amount),
            family_amount=_parse_optional_decimal(family_amount),
            expense_date=_parse_optional_datetime(expense_date),
            personal_savings_amount=_parse_optional_decimal(personal_savings_amount),
            personal_savings_user_id=_parse_optional_uuid(personal_savings_user_id),
            funding_sources=_parse_funding_sources(funding_sources),
            document_id=_parse_optional_uuid(document_id),
            show_doc_to_all=_parse_optional_bool(show_doc_to_all) if show_doc_to_all is not None else None,
            show_funding_to_family=_parse_optional_bool(show_funding_to_family)
            if show_funding_to_family is not None
            else None,
            doc_viewer_user_ids=parsed_doc_viewers,
            **kwargs
        )


# ---------------------------------------------------------------------------
# Expense log — List (paginated, limited fields)
# ---------------------------------------------------------------------------

class FamilyExpenseLogListItem(BaseModel):
    """Limited fields returned in the paginated expense log list."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    expense_name: str
    source_type: str
    expense_date: datetime
    added_by_user_id: UUID

    total_amount: Decimal
    family_amount: Decimal | None = None
    personal_savings_amount: Decimal | None = None
    personal_savings_user_id: UUID | None = None

    # Joined field — name of the user who earned this expense
    logged_by_user_name: str | None = None
    logged_by_user_id: UUID | None = None

    # Host family (populated on personal cross-family lists)
    family_id: UUID | None = None
    family_name: str | None = None

    # Document access
    document_id: UUID | None = None
    show_doc_to_all: bool = False
    doc_viewer_user_ids: list[UUID] = Field(default_factory=list)

    # Whether the current request user can edit this log
    can_edit: bool = False
    let_everyone_edit: bool = False
    has_breakdown: bool = False

    category_id: UUID | None = None
    category_name: str | None = None
    expense_made_for_user_id: UUID | None = None

    @computed_field
    def entry_done_by(self) -> UUID | None:
        return self.added_by_user_id or self.logged_by_user_id


class FamilyExpenseLogListResponse(PaginatedResponse[FamilyExpenseLogListItem]):
    """Paginated list of family expense logs (limited fields)."""


# ---------------------------------------------------------------------------
# Expense log — Full detail (for edit modal)
# ---------------------------------------------------------------------------

class FamilyExpenseLogDetailResponse(BaseModel):
    """Full detail of a family expense log record (for edit modal)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    family_id: UUID
    logged_by: UUID
    expense_name: str
    total_amount: Decimal
    family_amount: Decimal | None
    expense_date: datetime
    source_type: str
    source_id: UUID | None
    personal_savings_amount: Decimal | None
    personal_savings_user_id: UUID | None
    document_id: UUID | None
    added_by_user_id: UUID
    show_doc_to_all: bool
    let_everyone_edit: bool = False
    show_funding_to_family: bool = False
    funding_sources: list[FundingSourceInput] = Field(default_factory=list)
    doc_viewer_user_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    category_id: UUID | None = None
    expense_made_for_user_id: UUID | None = None

    @computed_field
    def entry_done_by(self) -> UUID | None:
        return self.added_by_user_id or self.logged_by


# ---------------------------------------------------------------------------
# Expense log — Create / Update responses
# ---------------------------------------------------------------------------

class FamilyExpenseLogCreateResponse(BaseModel):
    """Response after successfully creating a family expense log."""

    message: str
    log_id: UUID = Field(..., description="ID of the created expense log record")
    family_savings_updated: Decimal = Field(..., description="Amount added to family savings")
    personal_savings_updated: Decimal | None = Field(
        default=None,
        description="Amount added to personal savings, if applicable",
    )
    personal_savings_user_id: UUID | None = Field(
        default=None,
        description="User whose personal savings was updated",
    )


class FamilyExpenseLogUpdateResponse(BaseModel):
    """Response after successfully updating a family expense log."""

    message: str
    log_id: UUID = Field(..., description="ID of the updated expense log record")
    family_savings_updated: Decimal = Field(..., description="Net amount added to family savings")
    personal_savings_updated: Decimal | None = Field(
        default=None,
        description="Net amount added to personal savings, if applicable",
    )
    personal_savings_user_id: UUID | None = Field(
        default=None,
        description="User whose personal savings was updated",
    )


# ---------------------------------------------------------------------------
# Personal expense logs (user personal savings receipts)
# ---------------------------------------------------------------------------

class PersonalExpenseLogListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    expense_name: str
    amount: Decimal
    expense_date: datetime
    source_type: str
    family_id: UUID | None = None
    family_name: str | None = None
    family_expense_log_id: UUID | None = None
    document_id: UUID | None = None
    show_doc_to_all: bool = False
    can_edit: bool = False
    category_id: UUID | None = None
    category_name: str | None = None


class PersonalExpenseLogListResponse(PaginatedResponse[PersonalExpenseLogListItem]):
    pass


class PersonalExpenseLogDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    family_id: UUID | None
    user_id: UUID
    logged_by: UUID
    expense_name: str
    amount: Decimal
    expense_date: datetime
    source_type: str
    source_id: UUID | None
    family_expense_log_id: UUID | None
    family_amount: Decimal | None
    document_id: UUID | None
    show_doc_to_all: bool
    can_edit: bool = False
    category_id: UUID | None = None
    category_name: str | None = None
    created_at: datetime
    updated_at: datetime


class PersonalExpenseLogCreateRequest(BaseModel):
    expense_name: str = Field(..., min_length=1, max_length=255)
    amount: Decimal = Field(..., gt=0)
    expense_date: datetime
    show_doc_to_all: bool = False
    category_id: UUID | None = None

    @classmethod
    def as_form(
        cls,
        expense_name: Annotated[str, Form()],
        amount: Annotated[str, Form()],
        expense_date: Annotated[str, Form()],
        show_doc_to_all: Annotated[str | None, Form()] = None,
        category_id: Annotated[str | None, Form()] = None,
    ) -> Self:
        parsed_date = _parse_optional_datetime(expense_date)
        if parsed_date is None:
            raise ValueError("expense_date is required")
        parsed_amount = _parse_optional_decimal(amount)
        if parsed_amount is None or parsed_amount <= 0:
            raise ValueError("amount must be greater than zero")
        return cls(
            expense_name=expense_name.strip(),
            amount=parsed_amount,
            expense_date=parsed_date,
            show_doc_to_all=_parse_optional_bool(show_doc_to_all) or False,
            category_id=_parse_optional_uuid(category_id),
        )


class PersonalExpenseLogUpdateRequest(BaseModel):
    expense_name: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Decimal | None = Field(default=None, gt=0)
    expense_date: datetime | None = None
    show_doc_to_all: bool | None = None
    category_id: UUID | None = None

    @classmethod
    def as_form(
        cls,
        expense_name: Annotated[str | None, Form()] = None,
        amount: Annotated[str | None, Form()] = None,
        expense_date: Annotated[str | None, Form()] = None,
        show_doc_to_all: Annotated[str | None, Form()] = None,
        category_id: Annotated[str | None, Form()] = None,
    ) -> Self:
        parsed_amount = _parse_optional_decimal(amount) if amount is not None else None
        if parsed_amount is not None and parsed_amount <= 0:
            raise ValueError("amount must be greater than zero")
        return cls(
            expense_name=_empty_str_to_none(expense_name),
            amount=parsed_amount,
            expense_date=_parse_optional_datetime(expense_date),
            show_doc_to_all=_parse_optional_bool(show_doc_to_all),
            category_id=_parse_optional_uuid(category_id),
        )


class PersonalExpenseLogCreateResponse(BaseModel):
    message: str
    log_id: UUID
    personal_savings_updated: Decimal


class PersonalExpenseLogUpdateResponse(BaseModel):
    message: str
    log_id: UUID
    personal_savings_delta: Decimal


# ---------------------------------------------------------------------------
# Recurring expense — List responses
# ---------------------------------------------------------------------------

class FamilyRecurringExpenseSummaryListResponse(PaginatedResponse[FamilyRecurringExpenseSummary]):
    """Paginated summary of all family recurring expenses (visible to every family member)."""


class FamilyRecurringExpenseMineListResponse(PaginatedResponse[FamilyRecurringExpenseDetail]):
    """Paginated full-detail list of expenses added by the current user."""


class FamilyRecurringExpenseCreateResponse(BaseModel):
    """Response after successfully creating a family recurring expense."""

    message: str
    expense_id: UUID = Field(..., description="ID of the created expense record")
    document_id: UUID | None = Field(
        default=None,
        description="ID of the uploaded document, if one was provided",
    )


class FamilyRecurringExpenseUpdateResponse(BaseModel):
    """Response after successfully updating a family recurring expense."""

    message: str
    expense_id: UUID = Field(..., description="ID of the updated expense record")
    document_id: UUID | None = Field(
        default=None,
        description="ID of the updated document, if a new one was uploaded",
    )


RecurringExpenseMineListResponse = FamilyRecurringExpenseMineListResponse
RecurringExpenseCreateResponse = FamilyRecurringExpenseCreateResponse
RecurringExpenseUpdateResponse = FamilyRecurringExpenseUpdateResponse

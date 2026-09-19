"""Shared payload validators for job notification actions."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID


def validate_split_lines(
    lines: list[dict],
    expected_total: Decimal,
    *,
    owner_user_id: UUID | None = None,
    entity_family_id: UUID | None = None,
) -> list[dict]:
    if not lines:
        raise ValueError("splitLines is required")
    total = Decimal("0")
    for ln in lines:
        total += Decimal(str(ln.get("amount", "0")))
    if total != expected_total:
        raise ValueError(f"Split lines must sum to {expected_total}, got {total}")
    return lines


def validate_income_allocations(
    allocations: list[dict],
    personal_amount: Decimal,
    new_total: Decimal,
    *,
    allowed_family_ids: set[UUID],
) -> None:
    alloc_sum = Decimal("0")
    for row in allocations:
        family_id = row.get("familyId") or row.get("family_id")
        if family_id is None:
            raise ValueError("Each income allocation requires familyId")
        fid = UUID(str(family_id))
        if fid not in allowed_family_ids:
            raise ValueError(f"Family {fid} is not part of this income split")
        alloc_sum += Decimal(str(row.get("amount", "0")))
    if alloc_sum + personal_amount != new_total:
        raise ValueError(
            f"Allocations + personal must equal {new_total}, got {alloc_sum + personal_amount}"
        )

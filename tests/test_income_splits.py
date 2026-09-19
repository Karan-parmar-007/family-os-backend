from decimal import Decimal
from uuid import uuid4

import pytest

from app.api.routes.family_income.income_schemas import (
    FamilySplitInput,
    _validate_income_splits,
)


def test_validate_splits_ok():
    family_id = uuid4()
    _validate_income_splits(
        Decimal("100"),
        Decimal("40"),
        [FamilySplitInput(family_id=family_id, split_name="Salary", amount=Decimal("60"))],
    )


def test_validate_splits_must_equal_total():
    family_id = uuid4()
    with pytest.raises(ValueError, match="must add up"):
        _validate_income_splits(
            Decimal("100"),
            Decimal("30"),
            [FamilySplitInput(family_id=family_id, split_name="Salary", amount=Decimal("60"))],
        )


def test_validate_splits_rejects_duplicate_family():
    family_id = uuid4()
    split = FamilySplitInput(family_id=family_id, split_name="A", amount=Decimal("50"))
    with pytest.raises(ValueError, match="only be selected once"):
        _validate_income_splits(Decimal("100"), Decimal("50"), [split, split])


def test_validate_splits_rejects_unallocated_total():
    with pytest.raises(ValueError, match="must add up"):
        _validate_income_splits(Decimal("100"), Decimal("0"), [])


def test_validate_personal_only_ok():
    _validate_income_splits(Decimal("100"), Decimal("100"), [])

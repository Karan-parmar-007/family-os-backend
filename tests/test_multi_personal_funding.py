"""Additional coverage for multi-person personal funding and transfer scopes."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.api.schemas.funding import FundingSourceInput
from app.core.constants import POOL_FAMILY, POOL_PERSONAL
from app.core.funding_sources import (
    summarize_personal_funding,
    validate_log_funding_sources,
)
from app.api.routes.friend.model import canonical_user_pair
from app.api.routes.transfer.transfer_schemas import TransferCreateRequest


def test_funding_source_requires_user_id_for_personal():
    with pytest.raises(ValueError, match="user_id"):
        FundingSourceInput(pool_type=POOL_PERSONAL, amount=Decimal("10"))


def test_summarize_personal_funding_prefers_actor():
    actor = uuid4()
    other = uuid4()
    sources = [
        FundingSourceInput(pool_type=POOL_PERSONAL, user_id=other, amount=Decimal("30")),
        FundingSourceInput(pool_type=POOL_PERSONAL, user_id=actor, amount=Decimal("20")),
    ]
    total, user_id = summarize_personal_funding(sources, actor_user_id=actor)
    assert total == Decimal("50")
    assert user_id == actor


def test_validate_log_funding_sources_allows_multi_personal():
    family_id = uuid4()
    u1 = uuid4()
    u2 = uuid4()
    validate_log_funding_sources(
        Decimal("100"),
        [
            FundingSourceInput(pool_type=POOL_FAMILY, family_id=family_id, amount=Decimal("40")),
            FundingSourceInput(pool_type=POOL_PERSONAL, user_id=u1, amount=Decimal("30")),
            FundingSourceInput(pool_type=POOL_PERSONAL, user_id=u2, amount=Decimal("30")),
        ],
        family_id,
    )


def test_transfer_create_personal_to_personal_schema():
    req = TransferCreateRequest(
        from_scope="PERSONAL",
        to_scope="PERSONAL",
        to_user_id=uuid4(),
        from_user_id=uuid4(),
        amount=Decimal("25"),
    )
    assert req.to_family_id is None
    assert req.to_user_id is not None


def test_transfer_create_family_to_personal_schema():
    req = TransferCreateRequest(
        from_scope="FAMILY",
        to_scope="PERSONAL",
        to_user_id=uuid4(),
        amount=Decimal("10"),
    )
    assert req.to_scope == "PERSONAL"


def test_canonical_pair_stable():
    a = uuid4()
    b = uuid4()
    assert canonical_user_pair(a, b) == canonical_user_pair(b, a)

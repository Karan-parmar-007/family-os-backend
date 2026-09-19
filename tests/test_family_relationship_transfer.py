from decimal import Decimal

import pytest

from app.api.routes.family.model import Family
from app.api.routes.family_relationship.family_relationship_schemas import (
    FamilyConnectByCodeRequest,
)
from app.api.routes.family_relationship.family_relationship_service import (
    FamilyRelationshipService,
)
from app.api.routes.upcoming.upcoming_service import UpcomingService
from app.api.routes.transfer.transfer_schemas import TransferCreateRequest
from app.api.routes.transfer.transfer_service import TransferService
from app.api.routes.user.model import UserBase, UserFamilyLink
from app.core.constants import (
    LEDGER_IN,
    LEDGER_SOURCE_MANUAL,
    POOL_FAMILY,
    TRANSFER_STATUS_COMPLETED,
)
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef


@pytest.mark.integration
async def test_relationship_accept_and_uniqueness(db_session):
    import uuid, random
    suffix = uuid.uuid4().hex[:6]
    user_a = UserBase(email=f"rel-a-{suffix}@example.com", name="A", password="x")
    user_b = UserBase(email=f"rel-b-{suffix}@example.com", name="B", password="x")
    join_code_a = "".join(random.choices("0123456789", k=8))
    join_code_b = "".join(random.choices("0123456789", k=8))
    family_a = Family(name="Family A", currency="USD", join_code=join_code_a)
    family_b = Family(name="Family B", currency="USD", join_code=join_code_b)
    db_session.add_all([user_a, user_b, family_a, family_b])
    await db_session.flush()

    db_session.add(UserFamilyLink(user_id=user_a.id, family_id=family_a.id, is_family_manager=True))
    db_session.add(UserFamilyLink(user_id=user_b.id, family_id=family_b.id, is_family_manager=True))
    await db_session.commit()

    svc = FamilyRelationshipService(db_session)
    connected = await svc.connect_by_join_code(
        family_id=family_a.id,
        user_id=user_a.id,
        request=FamilyConnectByCodeRequest(join_code=family_b.join_code),
    )
    assert connected.status == "ACTIVE"

    with pytest.raises(ValueError):
        await svc.connect_by_join_code(
            family_id=family_a.id,
            user_id=user_a.id,
            request=FamilyConnectByCodeRequest(join_code=family_b.join_code),
        )


@pytest.mark.integration
async def test_cross_family_transfer_moves_between_family_pools(db_session):
    import uuid, random
    suffix = uuid.uuid4().hex[:6]
    user_a = UserBase(email=f"tx-a-{suffix}@example.com", name="A", password="x")
    user_b = UserBase(email=f"tx-b-{suffix}@example.com", name="B", password="x")
    join_code_a = "".join(random.choices("0123456789", k=8))
    join_code_b = "".join(random.choices("0123456789", k=8))
    family_a = Family(name="Source Family", currency="USD", join_code=join_code_a)
    family_b = Family(name="Target Family", currency="USD", join_code=join_code_b)
    db_session.add_all([user_a, user_b, family_a, family_b])
    await db_session.flush()

    db_session.add(UserFamilyLink(user_id=user_a.id, family_id=family_a.id, is_family_manager=True))
    db_session.add(UserFamilyLink(user_id=user_b.id, family_id=family_b.id, is_family_manager=True))
    await db_session.commit()

    relationship_service = FamilyRelationshipService(db_session)
    await relationship_service.connect_by_join_code(
        family_id=family_a.id,
        user_id=user_a.id,
        request=FamilyConnectByCodeRequest(join_code=family_b.join_code),
    )

    ledger = SavingsLedgerService(db_session)
    await ledger.apply_movement(
        SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_a.id),
        Decimal("1000"),
        LEDGER_IN,
        LEDGER_SOURCE_MANUAL,
    )
    await db_session.commit()

    transfer_service = TransferService(db_session)
    transfer = await transfer_service.create_transfer(
        family_id=family_a.id,
        created_by=user_a.id,
        request=TransferCreateRequest(
            to_family_id=family_b.id,
            from_scope="FAMILY",
            to_scope="FAMILY",
            amount=Decimal("125"),
        ),
    )
    assert transfer.status == TRANSFER_STATUS_COMPLETED

    source_row = await ledger._get_or_create_pool_row(
        SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_a.id)
    )
    target_row = await ledger._get_or_create_pool_row(
        SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_b.id)
    )
    assert source_row.total_savings == Decimal("875")
    assert target_row.total_savings == Decimal("125")


@pytest.mark.integration
async def test_upcoming_includes_recurring_cross_family_transfer(db_session):
    import uuid, random
    suffix = uuid.uuid4().hex[:6]
    user_a = UserBase(email=f"up-a-{suffix}@example.com", name="A", password="x")
    user_b = UserBase(email=f"up-b-{suffix}@example.com", name="B", password="x")
    join_code_a = "".join(random.choices("0123456789", k=8))
    join_code_b = "".join(random.choices("0123456789", k=8))
    family_a = Family(name="Origin Family", currency="USD", join_code=join_code_a)
    family_b = Family(name="Linked Family", currency="USD", join_code=join_code_b)
    db_session.add_all([user_a, user_b, family_a, family_b])
    await db_session.flush()

    db_session.add(UserFamilyLink(user_id=user_a.id, family_id=family_a.id, is_family_manager=True))
    db_session.add(UserFamilyLink(user_id=user_b.id, family_id=family_b.id, is_family_manager=True))
    await db_session.commit()

    relationship_service = FamilyRelationshipService(db_session)
    await relationship_service.connect_by_join_code(
        family_id=family_a.id,
        user_id=user_a.id,
        request=FamilyConnectByCodeRequest(join_code=family_b.join_code),
    )

    ledger = SavingsLedgerService(db_session)
    await ledger.apply_movement(
        SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_a.id),
        Decimal("500"),
        LEDGER_IN,
        LEDGER_SOURCE_MANUAL,
    )
    await db_session.commit()

    transfer_service = TransferService(db_session)
    transfer = await transfer_service.create_transfer(
        family_id=family_a.id,
        created_by=user_a.id,
        request=TransferCreateRequest(
            to_family_id=family_b.id,
            from_scope="FAMILY",
            to_scope="FAMILY",
            amount=Decimal("50"),
            is_recurring=True,
            recurring_every="MONTHLY",
        ),
    )
    transfer.next_run_date = transfer.created_at
    await db_session.commit()

    upcoming_service = UpcomingService(db_session)
    items = await upcoming_service.project_upcoming(
        family_id=family_a.id,
        user_id=user_a.id,
        horizon_days=30,
    )

    recurring_transfer = next(
        item for item in items if item.source_type == "TRANSFER" and item.source_id == transfer.id
    )
    assert recurring_transfer.type == "AUTO_TRANSFER"
    assert recurring_transfer.name == "Recurring transfer to Linked Family"

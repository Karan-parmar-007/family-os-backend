"""Rewrite coverage: 18:00 snap and transfer offers are not auto-debited."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.tz_eighteen import at_eighteen_utc
from app.core.constants import TRANSFER_STATUS_PENDING


def test_at_eighteen_kolkata_is_1230_utc():
    when = datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc)
    snapped = at_eighteen_utc(when, "Asia/Kolkata")
    assert snapped.hour == 12
    assert snapped.minute == 30


def _transfer_service(via_code: bool):
    from app.api.routes.transfer.transfer_service import TransferService

    svc = TransferService(MagicMock())
    svc._existing_by_key = AsyncMock(return_value=None)
    svc._is_member = AsyncMock(return_value=True)
    svc._resolve_destination = AsyncMock(return_value=(uuid4(), None, via_code))
    svc._notify_offer = AsyncMock()
    svc.execute_transfer_run = AsyncMock()
    svc.pg_session.add = MagicMock()
    svc.pg_session.flush = AsyncMock()
    svc.pg_session.commit = AsyncMock()
    svc.pg_session.refresh = AsyncMock()
    return svc


def _family_request():
    from app.api.routes.transfer.transfer_schemas import TransferCreateRequest

    return TransferCreateRequest(
        from_scope="FAMILY", to_scope="FAMILY", to_family_id=uuid4(), amount=Decimal("10")
    )


@pytest.mark.asyncio
async def test_direct_transfer_executes_immediately():
    svc = _transfer_service(via_code=False)
    await svc.create_transfer(uuid4(), uuid4(), _family_request())
    svc.execute_transfer_run.assert_awaited_once()
    svc._notify_offer.assert_not_awaited()


@pytest.mark.asyncio
async def test_code_transfer_waits_for_receiver():
    svc = _transfer_service(via_code=True)
    result = await svc.create_transfer(uuid4(), uuid4(), _family_request())
    svc.execute_transfer_run.assert_not_awaited()
    svc._notify_offer.assert_awaited_once()
    assert result.status == TRANSFER_STATUS_PENDING
    assert result.via_code is True


def test_fos_tick_accepts_force_flag():
    import inspect
    from app.scheduler.fos_tick import run_fos_tick

    assert "force" in inspect.signature(run_fos_tick).parameters


def test_sso_mongo_id_is_not_a_uuid():
    from uuid import UUID

    with pytest.raises(ValueError):
        UUID("507f1f77bcf86cd799439011")

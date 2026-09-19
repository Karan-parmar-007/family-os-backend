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


@pytest.mark.asyncio
async def test_transfer_create_does_not_execute():
    from app.api.routes.transfer.transfer_service import TransferService
    from app.api.routes.transfer.transfer_schemas import TransferCreateRequest

    svc = TransferService(MagicMock())
    svc._validate_and_gate = AsyncMock()
    svc.execute_transfer_run = AsyncMock()
    svc.pg_session.add = MagicMock()
    svc.pg_session.flush = AsyncMock()
    svc.pg_session.commit = AsyncMock()
    svc.pg_session.refresh = AsyncMock()

    req = TransferCreateRequest(
        from_scope="FAMILY",
        to_scope="FAMILY",
        to_family_id=uuid4(),
        amount=Decimal("10"),
    )
    result = await svc.create_transfer(uuid4(), uuid4(), req)
    svc.execute_transfer_run.assert_not_awaited()
    assert result.status == TRANSFER_STATUS_PENDING


def test_fos_tick_accepts_force_flag():
    import inspect
    from app.scheduler.fos_tick import run_fos_tick

    assert "force" in inspect.signature(run_fos_tick).parameters


def test_sso_mongo_id_is_not_a_uuid():
    from uuid import UUID

    with pytest.raises(ValueError):
        UUID("507f1f77bcf86cd799439011")

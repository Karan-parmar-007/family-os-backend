"""Shared completion helpers (Plan 11)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Awaitable, Callable
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.core.constants import NOTIF_STATUS_UNREAD

logger = logging.getLogger(__name__)


class BlockedByDefaultsError(Exception):
    """Raised when completion is blocked by open default-bucket entries."""


async def complete_entity(
    session: AsyncSession,
    *,
    entity,
    entity_type: str,
    terminal_status: str,
    notify_user_ids: list[UUID],
    title: str,
    body: str,
    email_fn: Callable[[AsyncSession], Awaitable[None]] | None = None,
    check_defaults: bool = True,
) -> None:
    """Mark an entity complete, cancel pending jobs, notify users, enqueue email."""
    if check_defaults:
        from app.core.default_bucket_service import DefaultBucketService

        open_total = await DefaultBucketService(session).total_open(
            entity_type, entity.id
        )
        if open_total > 0:
            raise BlockedByDefaultsError(
                f"Cannot complete {entity_type} while default bucket has open entries"
            )

    entity.status = terminal_status
    if hasattr(entity, "completed_at"):
        entity.completed_at = datetime.now(timezone.utc)

    await session.execute(
        update(ScheduledJob)
        .where(
            ScheduledJob.source_type == entity_type,
            ScheduledJob.source_id == entity.id,
            ScheduledJob.status.in_(["SCHEDULED", "AWAITING_CONFIRMATION", "DELAYED"]),
        )
        .values(status="CANCELLED")
    )

    for user_id in notify_user_ids:
        session.add(
            Notification(
                user_id=user_id,
                family_id=getattr(entity, "family_id", None),
                type=f"{entity_type}_COMPLETED",
                title=title,
                body=body,
                related_entity_type=entity_type,
                related_entity_id=entity.id,
                allowed_actions={"actions": ["DISMISS"]},
                status=NOTIF_STATUS_UNREAD,
            )
        )

    if email_fn is not None:
        pending = session.info.setdefault("pending_emails", [])
        pending.append(email_fn)

    await session.flush()


async def flush_pending_emails(session: AsyncSession) -> None:
    """Send emails queued during a transaction (post-commit)."""
    pending = session.info.pop("pending_emails", [])
    for fn in pending:
        try:
            await fn(session)
        except Exception:
            logger.exception("Failed to send completion email")

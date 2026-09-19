import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.scheduler.model import Notification, ScheduledJob
from app.api.schemas.pagination import PaginationParams
from app.core.constants import NOTIF_STATUS_READ, NOTIF_STATUS_UNREAD
from app.core.job_action_service import JobActionService

logger = logging.getLogger(__name__)

_ACTIONABLE_ACTIONS = {
    "ACCEPT",
    "ADJUST_AMOUNT",
    "ACCEPT_WITH_SPLITS",
    "PAID_EXTERNALLY",
    "DECLINE_DELAY",
    "SKIP_PERIOD",
    "SKIP_DEFAULT",
    "SKIP_INCREASE",
    "REMOVE_RECURRING",
    "REMOVE_SOURCE",
}


class NotificationService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session
        self._actions = JobActionService(pg_session)

    async def list_notifications(
        self,
        user_id: UUID,
        pagination: PaginationParams,
        *,
        status: str | None = None,
        notif_type: str | None = None,
        actionable: bool | None = None,
    ) -> tuple[list[Notification], int]:
        filters = [Notification.user_id == user_id]
        if status:
            filters.append(Notification.status == status)
        if notif_type:
            filters.append(Notification.type == notif_type)
        if actionable:
            filters.append(Notification.status == NOTIF_STATUS_UNREAD)
            filters.append(Notification.related_job_id.is_not(None))

        count_stmt = select(func.count()).select_from(Notification).where(*filters)
        total = (await self.pg_session.execute(count_stmt)).scalar_one()

        stmt = (
            select(Notification)
            .where(*filters)
            .order_by(Notification.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
        items = list((await self.pg_session.execute(stmt)).scalars().all())
        if actionable:
            items = [n for n in items if self._is_actionable(n)]
            total = len(items)
        return items, total

    def _is_actionable(self, notification: Notification) -> bool:
        if notification.status != NOTIF_STATUS_UNREAD or not notification.related_job_id:
            return False
        actions = notification.allowed_actions
        if isinstance(actions, dict):
            actions = actions.get("actions", [])
        return any(a in _ACTIONABLE_ACTIONS for a in (actions or []))

    async def unread_counts(self, user_id: UUID) -> tuple[int, int]:
        stmt = select(Notification).where(
            Notification.user_id == user_id,
            Notification.status == NOTIF_STATUS_UNREAD,
        )
        notifications = list((await self.pg_session.execute(stmt)).scalars().all())
        actionable = sum(1 for n in notifications if self._is_actionable(n))
        return len(notifications), actionable

    async def unread_count(self, user_id: UUID) -> int:
        count, _ = await self.unread_counts(user_id)
        return count

    async def get_notification(
        self, notification_id: UUID, user_id: UUID
    ) -> Notification | None:
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        return (await self.pg_session.execute(stmt)).scalar_one_or_none()

    async def mark_read(self, notification: Notification) -> Notification:
        notification.status = NOTIF_STATUS_READ
        await self.pg_session.commit()
        await self.pg_session.refresh(notification)
        return notification

    async def mark_all_read(self, user_id: UUID) -> int:
        stmt = select(Notification).where(
            Notification.user_id == user_id,
            Notification.status == NOTIF_STATUS_UNREAD,
        )
        notifications = list((await self.pg_session.execute(stmt)).scalars().all())
        for n in notifications:
            n.status = NOTIF_STATUS_READ
        await self.pg_session.commit()
        return len(notifications)

    async def take_action(
        self,
        notification: Notification,
        action: str,
        *,
        delay_days: int | None = None,
        payload: dict | None = None,
    ) -> Notification:
        job: ScheduledJob | None = None
        if notification.related_job_id:
            stmt = select(ScheduledJob).where(
                ScheduledJob.id == notification.related_job_id
            )
            job = (await self.pg_session.execute(stmt)).scalar_one_or_none()

        if job is None and action != "DISMISS":
            raise ValueError("Notification has no related job")

        if job is not None:
            await self._actions.apply_action(
                job,
                notification,
                action,
                delay_days=delay_days,
                actor_user_id=notification.user_id,
                payload=payload,
            )
        elif action == "DISMISS":
            notification.status = "DISMISSED"
            notification.action_taken = action
            notification.actioned_at = datetime.now(timezone.utc)

        await self.pg_session.commit()
        await self.pg_session.refresh(notification)
        return notification

import json
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sse_starlette.sse import EventSourceResponse

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.dependencies import NotificationServiceDep
from app.api.routes.notification.notification_events import (
    publish_notification_event,
    subscribe,
    unsubscribe,
)
from app.api.routes.notification.notification_schemas import (
    MessageResponse,
    NotificationActionRequest,
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)
from app.api.schemas.pagination import PaginationDep
from app.config import feature_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _require_notifications() -> None:
    if not feature_settings.FEATURE_NOTIFICATIONS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    current_user: LoggedInUserDep,
    notification_service: NotificationServiceDep,
    pagination: PaginationDep,
    notif_status: str | None = Query(default=None, alias="status"),
    notif_type: str | None = Query(default=None, alias="type"),
    actionable: bool | None = Query(default=None),
) -> NotificationListResponse:
    _require_notifications()
    items, total = await notification_service.list_notifications(
        current_user.id,
        pagination,
        status=notif_status,
        notif_type=notif_type,
        actionable=actionable,
    )
    return NotificationListResponse.from_page(
        [NotificationResponse.from_model(i) for i in items],
        total=total,
        pagination=pagination,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    current_user: LoggedInUserDep,
    notification_service: NotificationServiceDep,
) -> UnreadCountResponse:
    _require_notifications()
    count, actionable_count = await notification_service.unread_counts(current_user.id)
    return UnreadCountResponse(count=count, actionable_count=actionable_count)


@router.post("/{notification_id}/action", response_model=NotificationResponse)
async def notification_action(
    notification_id: UUID,
    request: NotificationActionRequest,
    current_user: LoggedInUserDep,
    notification_service: NotificationServiceDep,
) -> NotificationResponse:
    _require_notifications()
    notification = await notification_service.get_notification(
        notification_id, current_user.id
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        payload_dict = None
        if request.payload:
            payload_dict = request.payload.model_dump(by_alias=False, exclude_none=True)
        updated = await notification_service.take_action(
            notification,
            request.action,
            delay_days=request.delay_days,
            payload=payload_dict,
        )
        await publish_notification_event(
            current_user.id,
            {"type": "action_taken", "notificationId": str(updated.id)},
        )
        return NotificationResponse.from_model(updated)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        await notification_service.pg_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{notification_id}/read", response_model=MessageResponse)
async def mark_notification_read(
    notification_id: UUID,
    current_user: LoggedInUserDep,
    notification_service: NotificationServiceDep,
) -> MessageResponse:
    _require_notifications()
    notification = await notification_service.get_notification(
        notification_id, current_user.id
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await notification_service.mark_read(notification)
    return MessageResponse(message="Marked as read")


@router.post("/read-all", response_model=MessageResponse)
async def mark_all_read(
    current_user: LoggedInUserDep,
    notification_service: NotificationServiceDep,
) -> MessageResponse:
    _require_notifications()
    count = await notification_service.mark_all_read(current_user.id)
    return MessageResponse(message=f"Marked {count} notifications as read")


@router.get("/stream")
async def notification_stream(current_user: LoggedInUserDep):
    _require_notifications()

    queue = subscribe(current_user.id)

    async def event_generator():
        try:
            yield {
                "event": "connected",
                "data": json.dumps({"userId": str(current_user.id)}),
            }
            while True:
                data = await queue.get()
                yield {"event": "notification", "data": data}
        finally:
            unsubscribe(current_user.id, queue)

    return EventSourceResponse(event_generator())

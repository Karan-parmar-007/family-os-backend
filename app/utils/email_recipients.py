"""Resolve owner email for finance notification emails."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.user.model import UserBase


async def resolve_user_email(session: AsyncSession, user_id: UUID | None) -> str | None:
    if user_id is None:
        return None
    row = (
        await session.execute(select(UserBase.email).where(UserBase.id == user_id))
    ).scalar_one_or_none()
    return row

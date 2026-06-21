import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.user.model import UserBase
from app.api.routes.user.user_schemas import UserMeUpdate

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, pg_session: AsyncSession) -> None:
        self.pg_session = pg_session

    async def update_me(self, user: UserBase, req: UserMeUpdate) -> UserBase:
        update_data = req.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)

        await self.pg_session.commit()
        await self.pg_session.refresh(user)
        return user

    async def get_user(self, user_id: UUID) -> UserBase | None:
        stmt = select(UserBase).where(UserBase.id == user_id)
        result = await self.pg_session.execute(stmt)
        return result.scalar_one_or_none()

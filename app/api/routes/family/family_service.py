import asyncio
import logging
from typing import Any
from uuid import UUID

from pymongo.asynchronous.database import AsyncDatabase
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.garage_session import check_connectivity
from app.api.routes.family.model import Family, UserFamilyLink
from app.api.routes.user.model import UserBase

logger = logging.getLogger(__name__)


class FamilyService:
    def __init__(
        self,
        pg_session: AsyncSession,
        mongo_db: AsyncDatabase,
        garage_client: Any,
    ):
        self.pg_session = pg_session
        self.mongo_db = mongo_db
        self.garage_client = garage_client

    async def create_family(
        self,
        user_id: UUID,
        family_name: str,
        currency: str = "USD",
    ) -> tuple[Family, UserFamilyLink]:
        """Create a new family and link the creator as the family manager."""
        # Create the family
        new_family = Family(
            name=family_name,
            currency=currency,
        )
        self.pg_session.add(new_family)
        await self.pg_session.flush()  # Get the family ID

        # Link the user as family manager
        user_family_link = UserFamilyLink(
            user_id=user_id,
            family_id=new_family.id,
            is_family_manager=True,
        )
        self.pg_session.add(user_family_link)

        await self.pg_session.commit()
        await self.pg_session.refresh(new_family)
        await self.pg_session.refresh(user_family_link)

        return new_family, user_family_link

    # Example method, you can implement your family-related logic here
    async def get_family_info(self, family_id: str):
        # Implement logic to retrieve family information from the database
        pass
import asyncio
import logging
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.garage_session import check_connectivity

logger = logging.getLogger(__name__)

HEALTH_CHECK_TIMEOUT_SECONDS = 5.0


class HealthService:
    def __init__(
        self,
        pg_session: AsyncSession,
        mongo_db: AsyncDatabase,
        garage_client: Any,
    ) -> None:
        self.pg_session = pg_session
        self.mongo_db = mongo_db
        self.garage_client = garage_client

    async def check_postgres(self) -> bool:
        return await self._run_check("postgres", self._check_postgres)

    async def check_mongodb(self) -> bool:
        return await self._run_check("mongodb", self._check_mongodb)

    async def check_garage(self) -> bool:
        return await self._run_check("garage", self._check_garage)

    async def _run_check(self, name: str, check) -> bool:
        try:
            return await asyncio.wait_for(
                check(),
                timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning("%s health check timed out after %ss", name, HEALTH_CHECK_TIMEOUT_SECONDS)
            return False
        except Exception:
            logger.exception("%s health check failed", name)
            return False

    async def _check_postgres(self) -> bool:
        await self.pg_session.execute(text("SELECT 1"))
        return True

    async def _check_mongodb(self) -> bool:
        await self.mongo_db.command("ping")
        return True

    async def _check_garage(self) -> bool:
        return await check_connectivity(self.garage_client)

# app/api/dependencies.py

from typing import Annotated

from fastapi import Depends

from app.api.db_dependencies import GarageClientDep, MongoDBDep, PGSessionDep
from app.api.routes.health.health_service import HealthService


async def get_health_service(
    session: PGSessionDep,
    mongo: MongoDBDep,
    garage_client: GarageClientDep,
) -> HealthService:
    return HealthService(
        pg_session=session,
        mongo_db=mongo,
        garage_client=garage_client,
    )


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]

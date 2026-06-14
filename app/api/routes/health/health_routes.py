import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import HealthServiceDep
from app.api.routes.health.health_schemas import (
    DependencyStatus,
    HealthStatus,
    LivenessResponse,
    ReadinessResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/health",
    tags=["health"],
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@router.get(
    "/live",
    summary="Liveness probe",
    response_model=LivenessResponse,
    response_description="Application process is running",
)
async def liveness_check() -> LivenessResponse:
    """Kubernetes-style liveness probe — no external dependencies."""
    return LivenessResponse(status=HealthStatus.HEALTHY, timestamp=_utc_now())


@router.get(
    "/ready",
    summary="Readiness probe",
    response_model=ReadinessResponse,
    response_description="Application and all backing stores are reachable",
    responses={503: {"description": "One or more dependencies are unavailable"}},
)
async def readiness_check(health_service: HealthServiceDep) -> ReadinessResponse:
    """Kubernetes-style readiness probe — verifies Postgres, MongoDB, and Garage."""
    try:
        pg_ok, mongo_ok, garage_ok = await asyncio.gather(
            health_service.check_postgres(),
            health_service.check_mongodb(),
            health_service.check_garage(),
        )
    except Exception:
        logger.exception("readiness check failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Readiness check failed",
        )

    response = ReadinessResponse(
        status=HealthStatus.HEALTHY
        if pg_ok and mongo_ok and garage_ok
        else HealthStatus.UNHEALTHY,
        postgres=DependencyStatus.CONNECTED if pg_ok else DependencyStatus.DISCONNECTED,
        mongodb=DependencyStatus.CONNECTED if mongo_ok else DependencyStatus.DISCONNECTED,
        garage=DependencyStatus.CONNECTED if garage_ok else DependencyStatus.DISCONNECTED,
        timestamp=_utc_now(),
    )

    if response.status == HealthStatus.UNHEALTHY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response.model_dump(mode="json"),
        )

    return response

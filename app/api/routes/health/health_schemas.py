from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class DependencyStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class LivenessResponse(BaseModel):
    status: HealthStatus
    timestamp: datetime = Field(description="UTC timestamp of the check")


class ReadinessResponse(BaseModel):
    status: HealthStatus
    postgres: DependencyStatus
    mongodb: DependencyStatus
    garage: DependencyStatus = Field(description="Garage object storage")
    timestamp: datetime

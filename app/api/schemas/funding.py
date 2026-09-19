from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.constants import POOL_FAMILY, POOL_PERSONAL


class FundingSourceInput(BaseModel):
    pool_type: str
    family_id: UUID | None = None
    user_id: UUID | None = None
    amount: Decimal = Field(..., gt=0)

    @field_validator("pool_type", mode="before")
    @classmethod
    def normalize_pool_type(cls, value: str) -> str:
        if value == "GLOBAL_PERSONAL":
            return POOL_PERSONAL
        return value

    @model_validator(mode="after")
    def validate_fields(self) -> "FundingSourceInput":
        if self.pool_type == POOL_FAMILY:
            if self.family_id is None:
                raise ValueError("family_id is required when pool_type is FAMILY")
            if self.user_id is not None:
                raise ValueError("user_id must be omitted when pool_type is FAMILY")
        elif self.pool_type == POOL_PERSONAL:
            if self.family_id is not None:
                raise ValueError("family_id must be omitted when pool_type is PERSONAL")
            if self.user_id is None:
                raise ValueError("user_id is required when pool_type is PERSONAL")
        else:
            raise ValueError("pool_type must be FAMILY or PERSONAL")
        return self

from pydantic import BaseModel, Field


# -----------------------------------------------
# Request Schemas
# -----------------------------------------------

class FamilyCreateRequest(BaseModel):
    """Schema for creating a new family."""
    name: str = Field(..., min_length=1, max_length=255, description="Name of the family")
    currency: str = Field(default="USD", max_length=3, description="Currency code (e.g., USD, INR)")


# -----------------------------------------------
# Response Schemas
# -----------------------------------------------

class FamilyCreateResponse(BaseModel):
    """Simple success response after creating a family."""
    message: str




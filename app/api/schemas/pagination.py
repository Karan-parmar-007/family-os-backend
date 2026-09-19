from typing import Annotated, Generic, Self, TypeVar

from fastapi import Depends, Query
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Shared query pagination parameters."""

    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=10, ge=1, le=100, description="Number of items per page")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated API response."""

    items: list[T] = Field(..., description="Records for the current page")
    total: int = Field(..., description="Total number of records across all pages")
    page: int = Field(..., description="Current page number (1-indexed)")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total number of pages available")

    @classmethod
    def from_page(
        cls,
        items: list[T],
        *,
        total: int,
        pagination: PaginationParams,
    ) -> Self:
        total_pages = (total + pagination.page_size - 1) // pagination.page_size if total > 0 else 0
        return cls(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            total_pages=total_pages,
        )


def get_pagination_params(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=10, ge=1, le=100, description="Number of items per page"),
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)


type PaginationDep = Annotated[PaginationParams, Depends(get_pagination_params)]

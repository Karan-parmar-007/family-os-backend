"""Dependency chain: login → recurring income owner (user_id)."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.db_dependencies import PGSessionDep
from app.api.routes.family_income.model import RecurringIncome
from app.api.routes.user.model import UserBase


async def get_logged_in_recurring_income_owner(
    current_user: LoggedInUserDep,
    income_id: UUID,
    session: PGSessionDep,
) -> tuple[UserBase, RecurringIncome]:
    stmt = select(RecurringIncome).where(RecurringIncome.id == income_id)
    income = (await session.execute(stmt)).scalar_one_or_none()
    if income is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurring income not found",
        )
    if income.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can edit this recurring income",
        )
    return current_user, income


type LoggedInRecurringIncomeOwnerDep = Annotated[
    tuple[UserBase, RecurringIncome],
    Depends(get_logged_in_recurring_income_owner),
]


# Legacy family-scoped owner (unused by new routes; kept for compatibility during migration)
async def get_logged_in_income_owner(
    current_user: LoggedInUserDep,
    income_id: UUID,
    family_id: UUID,
    session: PGSessionDep,
) -> tuple[UserBase, RecurringIncome]:
    stmt = select(RecurringIncome).where(RecurringIncome.id == income_id)
    income = (await session.execute(stmt)).scalar_one_or_none()
    if income is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurring income not found",
        )
    if income.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can edit this recurring income",
        )
    return current_user, income


type LoggedInIncomeOwnerDep = Annotated[
    tuple[UserBase, RecurringIncome],
    Depends(get_logged_in_income_owner),
]

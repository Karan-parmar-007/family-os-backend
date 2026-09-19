"""Dependency chain: login → recurring expense owner (user_id)."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.db_dependencies import PGSessionDep
from app.api.routes.family_expense.model import RecurringExpense
from app.api.routes.user.model import UserBase


async def get_logged_in_recurring_expense_owner(
    current_user: LoggedInUserDep,
    expense_id: UUID,
    session: PGSessionDep,
) -> tuple[UserBase, RecurringExpense]:
    stmt = select(RecurringExpense).where(RecurringExpense.id == expense_id)
    expense = (await session.execute(stmt)).scalar_one_or_none()
    if expense is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recurring expense not found",
        )
    if expense.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can edit this recurring expense",
        )
    return current_user, expense


type LoggedInRecurringExpenseOwnerDep = Annotated[
    tuple[UserBase, RecurringExpense],
    Depends(get_logged_in_recurring_expense_owner),
]

from typing import ClassVar, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, SQLModel, func
from sqlalchemy import Column, DateTime, UniqueConstraint


class RecurringExpense(SQLModel, table=True):
    __tablename__: ClassVar[str] = "recurring_expenses"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    category_id: Optional[UUID] = Field(
        default=None, foreign_key="family_expense_categories.id"
    )

    expense_name: str = Field(max_length=255)
    total_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    personal_savings_amount: Optional[Decimal] = Field(
        default=None, max_digits=12, decimal_places=2
    )

    paid_every: Optional[str] = Field(default=None)
    repeat_interval_days: Optional[int] = Field(default=None)
    repeat_interval_months: Optional[int] = Field(default=None)
    repeat_interval_years: Optional[int] = Field(default=None)

    next_payment_date: Optional[datetime] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")

    show_docs_to_all: bool = Field(default=False)
    repeat_doc_with_logs: bool = Field(default=False)

    is_family_managed: bool = Field(default=False)
    let_everyone_edit: bool = Field(default=False)

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


FamilyRecurringExpense = RecurringExpense


class RecurringExpenseFamilySplit(SQLModel, table=True):
    __tablename__: ClassVar[str] = "recurring_expense_family_splits"
    __table_args__ = (
        UniqueConstraint(
            "expense_id", "family_id", name="uq_recurring_expense_family_splits_expense_family"
        ),
    )

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    expense_id: UUID = Field(foreign_key="recurring_expenses.id", index=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    split_name: str = Field(max_length=255)
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class RecurringExpenseDocAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "recurring_expense_doc_access"

    expense_id: UUID = Field(foreign_key="recurring_expenses.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


FamilyRecurringExpenseDocAccess = RecurringExpenseDocAccess


class RecurringExpensePersonalSplit(SQLModel, table=True):
    __tablename__: ClassVar[str] = "recurring_expense_personal_splits"
    __table_args__ = (
        UniqueConstraint(
            "expense_id",
            "user_id",
            name="uq_recurring_expense_personal_splits_expense_user",
        ),
    )

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    expense_id: UUID = Field(foreign_key="recurring_expenses.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )


class FamilyExpenseLogDocAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_expense_log_doc_access_v2"

    log_id: UUID = Field(foreign_key="family_expense_logs.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
        )
    )

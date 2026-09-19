from typing import ClassVar, List, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, Relationship, SQLModel, func
from sqlalchemy import Column, DateTime


class FamilyExpenseCategory(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_expense_categories"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    category_name: str
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class FamilyExpense(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_expenses"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    expense_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    category_id: Optional[UUID] = Field(default=None, foreign_key="family_expense_categories.id")
    is_recurring: bool = Field(default=False)
    paid_every: Optional[str] = Field(default=None) # MONTHLY, WEEKLY
    next_payment_date: Optional[datetime] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    added_by_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    expense_made_for_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    
    access_level: str = Field(default="FAMILY") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class FamilyExpenseAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_expense_access"

    expense_id: UUID = Field(foreign_key="family_expenses.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class ExcludeFromFamilyExpenses(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_expenses"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    expense_id: UUID = Field(foreign_key="family_expenses.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class PersonalExpense(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_expenses"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    user_id: UUID = Field(foreign_key="users.id")
    expense_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    category_id: Optional[UUID] = Field(default=None, foreign_key="family_expense_categories.id")
    is_recurring: bool = Field(default=False)
    paid_every: Optional[str] = Field(default=None) # MONTHLY, WEEKLY
    next_payment_date: Optional[datetime] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    deducted_from: Optional[str] = Field(default=None) # e.g. "PERSONAL_SAVINGS", "FAMILY_INCOME"
    expense_made_for_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    
    access_level: str = Field(default="PRIVATE") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class PersonalExpenseAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_expense_access"

    expense_id: UUID = Field(foreign_key="personal_expenses.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilyExpenseLog(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_expense_logs"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    logged_by: UUID = Field(foreign_key="users.id")
    expense_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    total_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    family_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    personal_savings_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    personal_savings_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    category_id: Optional[UUID] = Field(default=None, foreign_key="family_expense_categories.id")
    expense_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    
    # Tracking the source of the expense (e.g. MANUAL, RECURRING, FAMILY_DEBT_EMI)
    source_type: str = Field(default="MANUAL")
    source_id: Optional[UUID] = Field(default=None) # UUID of the triggering record
    recurring_expense_family_split_id: Optional[UUID] = Field(
        default=None, foreign_key="recurring_expense_family_splits.id"
    )

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    added_by_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    expense_made_for_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    show_doc_to_all: bool = Field(default=False)
    let_everyone_edit: bool = Field(default=False)
    show_funding_to_family: bool = Field(default=False)
    access_level: str = Field(default="FAMILY") # PRIVATE, FAMILY, SELECTED
    
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilyExpenseLogAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_expense_log_access"

    expense_log_id: UUID = Field(foreign_key="family_expense_logs.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class ExcludeFromFamilyExpenseLogs(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_expense_logs"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    expense_log_id: UUID = Field(foreign_key="family_expense_logs.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalExpenseLog(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_expense_logs"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID | None = Field(default=None, foreign_key="families.id", index=True)
    scope_type: str = Field(default="FAMILY")

    user_id: UUID = Field(foreign_key="users.id")
    logged_by: UUID = Field(foreign_key="users.id")
    expense_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    category_id: Optional[UUID] = Field(default=None, foreign_key="family_expense_categories.id")
    expense_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    family_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    family_expense_log_id: Optional[UUID] = Field(
        default=None, foreign_key="family_expense_logs.id"
    )

    # Tracking the source of the personal expense (e.g. MANUAL, RECURRING, FAMILY_EXPENSE_LOG)
    source_type: str = Field(default="MANUAL")
    source_id: Optional[UUID] = Field(default=None)

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    show_doc_to_all: bool = Field(default=False)
    expense_made_for_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")
    access_level: str = Field(default="PRIVATE") # PRIVATE, FAMILY, SELECTED
    
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalExpenseLogAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_expense_log_access"

    expense_log_id: UUID = Field(foreign_key="personal_expense_logs.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

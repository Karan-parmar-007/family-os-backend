from typing import ClassVar, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, SQLModel, func
from sqlalchemy import Column, DateTime, UniqueConstraint


class FamilyIncomeCategory(SQLModel, table=True):
  __tablename__: ClassVar[str] = 'family_income_categories'

  id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
  family_id: UUID = Field(foreign_key='families.id', index=True)
  category_name: str
  created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  )
  updated_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
  )


class RecurringIncome(SQLModel, table=True):
  __tablename__: ClassVar[str] = 'recurring_incomes'

  id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
  user_id: UUID = Field(foreign_key='users.id', index=True)
  category_id: Optional[UUID] = Field(default=None, foreign_key='family_income_categories.id')
  added_by_user_id: Optional[UUID] = Field(default=None, foreign_key='users.id')

  income_name: str = Field(max_length=255)
  total_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
  personal_savings_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)

  received_every: Optional[str] = Field(default=None)
  repeat_interval_days: Optional[int] = Field(default=None)
  repeat_interval_months: Optional[int] = Field(default=None)
  repeat_interval_years: Optional[int] = Field(default=None)

  next_receiving_date: Optional[datetime] = Field(default=None)
  document_id: Optional[UUID] = Field(default=None, foreign_key='documents.id')

  show_docs_to_all: bool = Field(default=False)
  repeat_doc_with_logs: bool = Field(default=False)

  # True when created via family quick-add (family page). Personal page incomes stay False.
  is_family_managed: bool = Field(default=False)
  # Family-managed only: allow any family member with a split to edit.
  let_everyone_edit: bool = Field(default=False)

  created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  )
  updated_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
  )


# Backward-compatible alias while callers are migrated.
FamilyRecurringIncome = RecurringIncome


class RecurringIncomeFamilySplit(SQLModel, table=True):
  __tablename__: ClassVar[str] = 'recurring_income_family_splits'
  __table_args__ = (
    UniqueConstraint('income_id', 'family_id', name='uq_recurring_income_family_splits_income_family'),
  )

  id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
  income_id: UUID = Field(foreign_key='recurring_incomes.id', index=True)
  family_id: UUID = Field(foreign_key='families.id', index=True)
  split_name: str = Field(max_length=255)
  amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)

  created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  )
  updated_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
  )


class RecurringIncomeDocAccess(SQLModel, table=True):
  __tablename__: ClassVar[str] = 'recurring_income_doc_access'

  income_id: UUID = Field(foreign_key='recurring_incomes.id', primary_key=True)
  user_id: UUID = Field(foreign_key='users.id', primary_key=True)
  created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  )
  updated_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
  )


class RecurringIncomePersonalSplit(SQLModel, table=True):
  __tablename__: ClassVar[str] = 'recurring_income_personal_splits'
  __table_args__ = (
    UniqueConstraint('income_id', 'user_id', name='uq_recurring_income_personal_splits_income_user'),
  )

  id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
  income_id: UUID = Field(foreign_key='recurring_incomes.id', index=True)
  user_id: UUID = Field(foreign_key='users.id', index=True)
  amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)

  created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  )
  updated_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
  )


# Backward-compatible alias.
FamilyRecurringIncomeDocAccess = RecurringIncomeDocAccess


class FamilyIncomeLog(SQLModel, table=True):
  __tablename__: ClassVar[str] = 'family_income_logs'

  id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
  family_id: UUID = Field(foreign_key='families.id', index=True)
  scope_type: str = Field(default="FAMILY")

  logged_by: UUID = Field(foreign_key='users.id')
  income_name: str
  total_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
  family_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
  income_date: datetime = Field(
    sa_column=Column(DateTime(timezone=True), nullable=False)
  )

  source_type: str = Field(default='MANUAL')
  source_id: Optional[UUID] = Field(default=None)
  recurring_income_family_split_id: Optional[UUID] = Field(
    default=None, foreign_key='recurring_income_family_splits.id'
  )

  personal_savings_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
  personal_savings_user_id: Optional[UUID] = Field(default=None, foreign_key='users.id')
  earned_by_user_id: Optional[UUID] = Field(default=None, foreign_key='users.id')
  category_id: Optional[UUID] = Field(default=None, foreign_key='family_income_categories.id')
  document_id: Optional[UUID] = Field(default=None, foreign_key='documents.id')
  added_by_user_id: UUID = Field(foreign_key='users.id')

  show_doc_to_all: bool = Field(default=False)
  let_everyone_edit: bool = Field(default=False)
  show_funding_to_family: bool = Field(default=False)

  created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  )
  updated_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
  )


class FamilyIncomeLogDocAccess(SQLModel, table=True):
  __tablename__: ClassVar[str] = 'family_income_log_doc_access'

  log_id: UUID = Field(foreign_key='family_income_logs.id', primary_key=True)
  user_id: UUID = Field(foreign_key='users.id', primary_key=True)
  created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  )
  updated_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
  )


class PersonalIncomeLog(SQLModel, table=True):
  __tablename__: ClassVar[str] = 'personal_income_logs'

  id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
  family_id: UUID | None = Field(default=None, foreign_key='families.id', index=True)
  scope_type: str = Field(default="FAMILY")

  user_id: UUID = Field(foreign_key='users.id')
  logged_by: UUID = Field(foreign_key='users.id')
  income_name: str
  category_id: Optional[UUID] = Field(default=None, foreign_key='family_income_categories.id')
  amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
  income_date: datetime = Field(
    sa_column=Column(DateTime(timezone=True), nullable=False)
  )

  family_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
  family_income_log_id: Optional[UUID] = Field(default=None, foreign_key='family_income_logs.id')

  source_type: str = Field(default='MANUAL')
  source_id: Optional[UUID] = Field(default=None)

  document_id: Optional[UUID] = Field(default=None, foreign_key='documents.id')
  access_level: str = Field(default='PRIVATE')

  show_doc_to_all: bool = Field(default=False)

  created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  )
  updated_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
  )


class PersonalIncomeLogAccess(SQLModel, table=True):
  __tablename__: ClassVar[str] = 'personal_income_log_access'

  income_log_id: UUID = Field(foreign_key='personal_income_logs.id', primary_key=True)
  user_id: UUID = Field(foreign_key='users.id', primary_key=True)
  access_level: str = Field(default='READ')
  created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  )
  updated_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
  )

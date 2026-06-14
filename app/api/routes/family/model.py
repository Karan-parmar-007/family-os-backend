from typing import ClassVar, List, Optional
from datetime import datetime
from decimal import Decimal
from uuid import UUID
import uuid6
from sqlmodel import Field, Relationship, SQLModel
from sqlmodel import Field, Relationship, SQLModel, func
from sqlalchemy import Column, DateTime
from app.api.routes.user.model import UserBase, UserFamilyLink


class Document(SQLModel, table=True):
    __tablename__: ClassVar[str] = "documents"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    filename: Optional[str] = Field(default=None)
    file_path: Optional[str] = Field(default=None)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class Family(SQLModel, table=True):
    __tablename__: ClassVar[str] = "families"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    name: str
    currency: str = Field(default="USD")
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )

    users: List[UserBase] = Relationship(
        back_populates="families",
        link_model=UserFamilyLink,
    )

class FamilyTotalSavings(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_total_savings"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", unique=True)
    total_savings: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )

class PersonalTotalSavings(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_total_savings"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id")
    user_id: UUID = Field(foreign_key="users.id")
    total_savings: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )

# -----------------------------------------------
# Assets
# -----------------------------------------------


class FamilyAssets(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_assets"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id")
    asset_name: str
    type: str
    in_someone_name: Optional[UUID] = Field(default=None, foreign_key="users.id")
    is_increasing: bool = Field(default=False)
    increase_percentage: Optional[float] = Field(default=None) # Percentage (e.g., 2.0 for 2% increase)
    increase_every: Optional[str] = Field(default=None) # MONTHLY, QUARTERLY, YEARLY
    next_increase_date: Optional[datetime] = Field(default=None)
    has_emi: bool = Field(default=False)
    emi_amount: Optional[float] = Field(default=None)
    emi_every: Optional[str] = Field(default=None) # MONTHLY, WEEKLY
    emi_next_date: Optional[datetime] = Field(default=None)
    is_per_something: bool = Field(default=False)
    value_per_something: float = Field(default=0.0)
    quantity: int = Field(default=1)
    value: float = Field(default=0.0)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )


class ExcludeFromFamilyAssets(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_assets"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    asset_id: UUID = Field(foreign_key="family_assets.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilyAssetAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_asset_access"

    asset_id: UUID = Field(foreign_key="family_assets.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalAsset(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_assets"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id")
    asset_name: str
    type: str
    in_someone_name: Optional[UUID] = Field(default=None, foreign_key="users.id")
    is_increasing: bool = Field(default=False)
    increase_percentage: Optional[float] = Field(default=None) # Percentage (e.g., 2.0 for 2% increase)
    increase_every: Optional[str] = Field(default=None) # MONTHLY, QUARTERLY, YEARLY
    next_increase_date: Optional[datetime] = Field(default=None)
    has_emi: bool = Field(default=False)
    emi_amount: Optional[float] = Field(default=None)
    emi_every: Optional[str] = Field(default=None) # MONTHLY, WEEKLY
    emi_next_date: Optional[datetime] = Field(default=None)
    is_per_something: bool = Field(default=False)
    value_per_something: float = Field(default=0.0)
    quantity: int = Field(default=1)
    value: float = Field(default=0.0)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY") # PRIVATE, FAMILY, SELECTED
    deducted_from: Optional[str] = Field(default=None) # e.g. "PERSONAL_SAVINGS", "FAMILY_INCOME"
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )

class PersonalAssetAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_asset_access"

    asset_id: UUID = Field(foreign_key="personal_assets.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

# -----------------------------------------------
# Debts
# -----------------------------------------------

    
class FamilyDebt(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_debts"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    debt_name: str
    type: str  # e.g., "Credit Card", "Home Loan", "Personal"
    status: str = Field(default="ACTIVE") # ACTIVE, PAID, DEFAULTED
    debt_in_the_name_of: UUID = Field(foreign_key="users.id")
    
    # Financials (Using Decimal for precision)
    total_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    remaining_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    monthly_emi: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    
    # Interest details
    has_interest: bool = Field(default=False)
    interest_rate: Optional[float] = Field(default=None) # Percentage (e.g., 12.5)
    interest_type: Optional[str] = Field(default=None)  # "FLAT", "REDUCING" or "Increasing"
    interest_increase_every: Optional[str] = Field(default=None) # MONTHLY, QUARTERLY, YEARLY
    interest_increase_percentage: Optional[float] = Field(default=None) # Percentage (e.g., 2.0 for 2% increase)
    next_interest_increase_date: Optional[datetime] = Field(default=None)

    # Schedule
    has_installments: bool = Field(default=False)
    installments_every: Optional[str] = Field(default="MONTHLY") # MONTHLY, WEEKLY
    start_date: Optional[datetime] = Field(default=None)
    end_date: Optional[datetime] = Field(default=None)
    emi_next_date: Optional[datetime] = Field(default=None)
    
    # Metadata
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )



class FamilyDebtAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_debt_access"

    debt_id: UUID = Field(foreign_key="family_debts.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class ExcludeFromFamilyDebts(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_debts"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    debt_id: UUID = Field(foreign_key="family_debts.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class PersonalDebt(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_debts"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    user_id: UUID = Field(foreign_key="users.id")
    debt_name: str
    type: str  # e.g., "Credit Card", "Home Loan", "Personal"
    status: str = Field(default="ACTIVE") # ACTIVE, PAID, DEFAULTED
    
    # Financials (Using Decimal for precision)
    total_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    remaining_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    monthly_emi: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    
    # Interest details
    has_interest: bool = Field(default=False)
    interest_rate: Optional[float] = Field(default=None) # Percentage (e.g., 12.5)
    interest_type: Optional[str] = Field(default=None)  # "FLAT", "REDUCING" or "Increasing"
    interest_increase_every: Optional[str] = Field(default=None) # MONTHLY, QUARTERLY, YEARLY
    interest_increase_percentage: Optional[float] = Field(default=None) # Percentage (e.g., 2.0 for 2% increase)
    next_interest_increase_date: Optional[datetime] = Field(default=None)

    # Schedule
    has_installments: bool = Field(default=False)
    installments_every: Optional[str] = Field(default="MONTHLY") # MONTHLY, WEEKLY
    start_date: Optional[datetime] = Field(default=None)
    end_date: Optional[datetime] = Field(default=None)
    emi_next_date: Optional[datetime] = Field(default=None)
    deducted_from: Optional[str] = Field(default=None) # e.g. "PERSONAL_SAVINGS", "FAMILY_INCOME"
    
    # Metadata
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="PRIVATE") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalDebtAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_debt_access"

    debt_id: UUID = Field(foreign_key="personal_debts.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

# -----------------------------------------------
# Incomes
# -----------------------------------------------

class FamilyRecurringIncome(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_recurring_incomes"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    income_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    received_every: Optional[str] = Field(default=None) # MONTHLY, WEEKLY
    next_receiving_date: Optional[datetime] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    personal_savings_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2) # Amount that goes to personal savings
    personal_savings_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id") # Whose personal savings the carved-out amount routes to
    
    access_level: str = Field(default="FAMILY") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilyRecurringIncomeAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_recurring_income_access"

    income_id: UUID = Field(foreign_key="family_recurring_incomes.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class ExcludeFromFamilyRecurringIncomes(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_recurring_incomes"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    income_id: UUID = Field(foreign_key="family_recurring_incomes.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class FamilyIncomeLog(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_income_logs"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    logged_by: UUID = Field(foreign_key="users.id")
    income_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    income_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    
    # Tracking the source of the income (e.g. MANUAL, FAMILY_RECURRING_INCOME)
    source_type: str = Field(default="MANUAL")
    source_id: Optional[UUID] = Field(default=None) # UUID of the triggering record

    # Optional carve-out of this (possibly one-time) income into someone's personal savings
    personal_savings_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    personal_savings_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id")

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY") # PRIVATE, FAMILY, SELECTED
    
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class FamilyIncomeLogAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_income_log_access"

    income_log_id: UUID = Field(foreign_key="family_income_logs.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class ExcludeFromFamilyIncomeLogs(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_income_logs"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    income_log_id: UUID = Field(foreign_key="family_income_logs.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalRecurringIncome(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_recurring_incomes"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    user_id: UUID = Field(foreign_key="users.id")
    income_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    received_every: Optional[str] = Field(default=None) # MONTHLY, WEEKLY
    next_receiving_date: Optional[datetime] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    deducted_from: Optional[str] = Field(default=None) # e.g. "PERSONAL_SAVINGS", "FAMILY_INCOME"
    
    access_level: str = Field(default="PRIVATE") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class PersonalRecurringIncomeAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_recurring_income_access"

    income_id: UUID = Field(foreign_key="personal_recurring_incomes.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

class PersonalSavingslogs(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_savings_logs"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    user_id: UUID = Field(foreign_key="users.id")
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    
    access_level: str = Field(default="PRIVATE") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    ) 

class PersonalSavingsLogsAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_savings_logs_access"

    savings_id: UUID = Field(foreign_key="personal_savings_logs.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


# -----------------------------------------------
# Expenses
# -----------------------------------------------

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
    expense_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    category_id: Optional[UUID] = Field(default=None, foreign_key="family_expense_categories.id")
    is_recurring: bool = Field(default=False)
    paid_every: Optional[str] = Field(default=None) # MONTHLY, WEEKLY
    next_payment_date: Optional[datetime] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    
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
    user_id: UUID = Field(foreign_key="users.id")
    expense_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    category_id: Optional[UUID] = Field(default=None, foreign_key="family_expense_categories.id")
    is_recurring: bool = Field(default=False)
    paid_every: Optional[str] = Field(default=None) # MONTHLY, WEEKLY
    next_payment_date: Optional[datetime] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    deducted_from: Optional[str] = Field(default=None) # e.g. "PERSONAL_SAVINGS", "FAMILY_INCOME"
    
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
    logged_by: UUID = Field(foreign_key="users.id")
    expense_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    category_id: Optional[UUID] = Field(default=None, foreign_key="family_expense_categories.id")
    expense_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    
    # Tracking the source of the expense (e.g. MANUAL, FAMILY_EXPENSE, FAMILY_DEBT_EMI, FAMILY_ASSET_INVESTMENT)
    source_type: str = Field(default="MANUAL")
    source_id: Optional[UUID] = Field(default=None) # UUID of the triggering record

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
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
    family_id: UUID = Field(foreign_key="families.id", index=True)
    user_id: UUID = Field(foreign_key="users.id")
    logged_by: UUID = Field(foreign_key="users.id")
    expense_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    category_id: Optional[UUID] = Field(default=None, foreign_key="family_expense_categories.id")
    expense_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    
    # Tracking the source of the personal expense (e.g. MANUAL, PERSONAL_EXPENSE, PERSONAL_DEBT_EMI, PERSONAL_ASSET_INVESTMENT)
    source_type: str = Field(default="MANUAL")
    source_id: Optional[UUID] = Field(default=None) # UUID of the triggering record

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
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


# -----------------------------------------------
# Personal Income Logs
# -----------------------------------------------
# Symmetry with FamilyIncomeLog so a member's one-time / ad-hoc personal income
# can be recorded and selectively shared. Feature 11 isolation lives here: a
# person grants per-record access, so (for example) a mother only sees the
# specific personal incomes/savings she was given access to — never the total.

class PersonalIncomeLog(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_income_logs"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    user_id: UUID = Field(foreign_key="users.id") # Owner of this personal income
    logged_by: UUID = Field(foreign_key="users.id")
    income_name: str
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    income_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    # Optional carve-out of this income into the owner's personal savings
    personal_savings_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)

    # Tracking the source (e.g. MANUAL, PERSONAL_RECURRING_INCOME, PERSONAL_GOAL_WITHDRAWAL)
    source_type: str = Field(default="MANUAL")
    source_id: Optional[UUID] = Field(default=None) # UUID of the triggering record

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="PRIVATE") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalIncomeLogAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_income_log_access"

    income_log_id: UUID = Field(foreign_key="personal_income_logs.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


# -----------------------------------------------
# Insurance
# -----------------------------------------------
# Covers any insurance type (HEALTH, LIFE, TERM, VEHICLE, HOME, TRAVEL, etc).
# Premiums can be funded through a SavingsPlan (sinking fund) below by linking
# a FamilySavingsPlan with purpose_type=INSURANCE -> linked_id = this row.

class FamilyInsurance(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_insurances"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    insurance_name: str
    type: str # HEALTH, LIFE, TERM, VEHICLE, HOME, TRAVEL, etc
    provider: Optional[str] = Field(default=None)
    policy_number: Optional[str] = Field(default=None)
    insured_member: Optional[UUID] = Field(default=None, foreign_key="users.id") # Whose life/asset is covered
    nominee: Optional[str] = Field(default=None)

    coverage_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2) # Sum assured
    premium_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    premium_every: Optional[str] = Field(default=None) # MONTHLY, QUARTERLY, HALF_YEARLY, YEARLY, ONE_TIME
    next_premium_date: Optional[datetime] = Field(default=None)
    start_date: Optional[datetime] = Field(default=None)
    end_date: Optional[datetime] = Field(default=None)
    maturity_date: Optional[datetime] = Field(default=None)
    maturity_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    status: str = Field(default="ACTIVE") # ACTIVE, LAPSED, MATURED, CLAIMED, CANCELLED

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilyInsuranceAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_insurance_access"

    insurance_id: UUID = Field(foreign_key="family_insurances.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class ExcludeFromFamilyInsurances(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_insurances"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    insurance_id: UUID = Field(foreign_key="family_insurances.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalInsurance(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_insurances"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    user_id: UUID = Field(foreign_key="users.id")
    insurance_name: str
    type: str # HEALTH, LIFE, TERM, VEHICLE, HOME, TRAVEL, etc
    provider: Optional[str] = Field(default=None)
    policy_number: Optional[str] = Field(default=None)
    insured_member: Optional[UUID] = Field(default=None, foreign_key="users.id")
    nominee: Optional[str] = Field(default=None)

    coverage_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    premium_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    premium_every: Optional[str] = Field(default=None) # MONTHLY, QUARTERLY, HALF_YEARLY, YEARLY, ONE_TIME
    next_premium_date: Optional[datetime] = Field(default=None)
    start_date: Optional[datetime] = Field(default=None)
    end_date: Optional[datetime] = Field(default=None)
    maturity_date: Optional[datetime] = Field(default=None)
    maturity_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    status: str = Field(default="ACTIVE") # ACTIVE, LAPSED, MATURED, CLAIMED, CANCELLED

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    deducted_from: Optional[str] = Field(default=None) # e.g. "PERSONAL_SAVINGS", "FAMILY_INCOME"
    access_level: str = Field(default="PRIVATE") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalInsuranceAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_insurance_access"

    insurance_id: UUID = Field(foreign_key="personal_insurances.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


# -----------------------------------------------
# Savings Plans (Sinking Funds / EMI-style accruals)
# -----------------------------------------------
# Feature 5: a big or lumpy payment (yearly health insurance, 6-monthly wifi,
# an investment, etc) is broken into smaller contributions. The user picks a
# contribution_amount + contribution_every (e.g. 3k monthly, or split across
# every 3 months) and we accrue into accumulated_amount until next_target_date,
# when the real bill is paid out of the fund.
#
# A plan can stand alone (purpose_type=GENERAL) or be attached to another
# record via (linked_type, linked_id) — e.g. linked_type="FAMILY_INSURANCE".

class FamilySavingsPlan(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_savings_plans"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    plan_name: str
    purpose_type: str = Field(default="GENERAL") # GENERAL, INSURANCE, EXPENSE, ASSET, INVESTMENT, DEBT
    linked_type: Optional[str] = Field(default=None) # e.g. FAMILY_INSURANCE, FAMILY_EXPENSE, FAMILY_ASSET, FAMILY_DEBT
    linked_id: Optional[UUID] = Field(default=None) # UUID of the linked record

    # The real bill we are saving toward
    target_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2) # e.g. 50k
    accumulated_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2) # Saved so far
    target_frequency: Optional[str] = Field(default=None) # How often the bill recurs: YEARLY, HALF_YEARLY, QUARTERLY
    next_target_date: Optional[datetime] = Field(default=None) # When the bill is next due

    # How we set money aside for it
    contribution_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2) # e.g. 3k
    contribution_every: str = Field(default="MONTHLY") # MONTHLY, QUARTERLY, WEEKLY
    next_contribution_date: Optional[datetime] = Field(default=None)
    auto_deduct: bool = Field(default=True) # Auto-accrue contribution on schedule
    deduct_at_period_start: bool = Field(default=True) # Deduct at start of the period
    funded_from: Optional[str] = Field(default=None) # e.g. "FAMILY_INCOME"
    status: str = Field(default="ACTIVE") # ACTIVE, PAUSED, COMPLETED, CANCELLED

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilySavingsPlanAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_savings_plan_access"

    plan_id: UUID = Field(foreign_key="family_savings_plans.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class ExcludeFromFamilySavingsPlans(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_savings_plans"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    plan_id: UUID = Field(foreign_key="family_savings_plans.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


# Ledger of each accrual into / payout from a family savings plan.
# Visibility is inherited from the parent FamilySavingsPlan (no separate
# access/exclude tables for sub-records).
class FamilySavingsPlanContribution(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_savings_plan_contributions"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    plan_id: UUID = Field(foreign_key="family_savings_plans.id", index=True)
    contributed_by: Optional[UUID] = Field(default=None, foreign_key="users.id")
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    direction: str = Field(default="IN") # IN (accrual), OUT (bill paid from fund)
    contribution_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    source_type: str = Field(default="MANUAL") # MANUAL, SCHEDULED
    source_id: Optional[UUID] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalSavingsPlan(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_savings_plans"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    user_id: UUID = Field(foreign_key="users.id")
    plan_name: str
    purpose_type: str = Field(default="GENERAL") # GENERAL, INSURANCE, EXPENSE, ASSET, INVESTMENT, DEBT
    linked_type: Optional[str] = Field(default=None) # e.g. PERSONAL_INSURANCE, PERSONAL_EXPENSE, PERSONAL_ASSET
    linked_id: Optional[UUID] = Field(default=None)

    target_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    accumulated_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    target_frequency: Optional[str] = Field(default=None) # YEARLY, HALF_YEARLY, QUARTERLY
    next_target_date: Optional[datetime] = Field(default=None)

    contribution_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    contribution_every: str = Field(default="MONTHLY") # MONTHLY, QUARTERLY, WEEKLY
    next_contribution_date: Optional[datetime] = Field(default=None)
    auto_deduct: bool = Field(default=True)
    deduct_at_period_start: bool = Field(default=True)
    funded_from: Optional[str] = Field(default=None) # e.g. "PERSONAL_SAVINGS", "FAMILY_INCOME"
    status: str = Field(default="ACTIVE") # ACTIVE, PAUSED, COMPLETED, CANCELLED

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="PRIVATE") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalSavingsPlanAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_savings_plan_access"

    plan_id: UUID = Field(foreign_key="personal_savings_plans.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalSavingsPlanContribution(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_savings_plan_contributions"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    plan_id: UUID = Field(foreign_key="personal_savings_plans.id", index=True)
    user_id: UUID = Field(foreign_key="users.id")
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    direction: str = Field(default="IN") # IN (accrual), OUT (bill paid from fund)
    contribution_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    source_type: str = Field(default="MANUAL") # MANUAL, SCHEDULED
    source_id: Optional[UUID] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


# -----------------------------------------------
# Goals
# -----------------------------------------------
# Feature 7: save toward a future purchase (house, car, etc). Like a savings
# plan but the target is a one-off purchase rather than a recurring bill. Money
# is gathered into collected_amount, optionally on a schedule, and members can
# also top it up manually as they save.

class FamilyGoal(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_goals"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    goal_name: str
    goal_type: Optional[str] = Field(default=None) # PROPERTY, VEHICLE, EDUCATION, TRAVEL, EMERGENCY, GENERAL
    target_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    collected_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    target_date: Optional[datetime] = Field(default=None)

    contribution_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2) # Planned per-period saving
    contribution_every: Optional[str] = Field(default="MONTHLY") # MONTHLY, QUARTERLY, WEEKLY
    next_contribution_date: Optional[datetime] = Field(default=None)
    auto_deduct: bool = Field(default=False)
    funded_from: Optional[str] = Field(default=None) # e.g. "FAMILY_INCOME"
    status: str = Field(default="ACTIVE") # ACTIVE, ACHIEVED, PAUSED, CANCELLED

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="FAMILY") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class FamilyGoalAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_goal_access"

    goal_id: UUID = Field(foreign_key="family_goals.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class ExcludeFromFamilyGoals(SQLModel, table=True):
    __tablename__: ClassVar[str] = "exclude_from_family_goals"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    goal_id: UUID = Field(foreign_key="family_goals.id")
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


# Ledger of contributions toward a family goal. Visibility inherited from parent.
class FamilyGoalContribution(SQLModel, table=True):
    __tablename__: ClassVar[str] = "family_goal_contributions"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    goal_id: UUID = Field(foreign_key="family_goals.id", index=True)
    contributed_by: Optional[UUID] = Field(default=None, foreign_key="users.id")
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    direction: str = Field(default="IN") # IN (saved toward goal), OUT (withdrawn)
    contribution_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    source_type: str = Field(default="MANUAL") # MANUAL, SCHEDULED
    source_id: Optional[UUID] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalGoal(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_goals"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    user_id: UUID = Field(foreign_key="users.id")
    goal_name: str
    goal_type: Optional[str] = Field(default=None) # PROPERTY, VEHICLE, EDUCATION, TRAVEL, EMERGENCY, GENERAL
    target_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    collected_amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    target_date: Optional[datetime] = Field(default=None)

    contribution_amount: Optional[Decimal] = Field(default=None, max_digits=12, decimal_places=2)
    contribution_every: Optional[str] = Field(default="MONTHLY") # MONTHLY, QUARTERLY, WEEKLY
    next_contribution_date: Optional[datetime] = Field(default=None)
    auto_deduct: bool = Field(default=False)
    funded_from: Optional[str] = Field(default=None) # e.g. "PERSONAL_SAVINGS", "FAMILY_INCOME"
    status: str = Field(default="ACTIVE") # ACTIVE, ACHIEVED, PAUSED, CANCELLED

    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    access_level: str = Field(default="PRIVATE") # PRIVATE, FAMILY, SELECTED
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalGoalAccess(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_goal_access"

    goal_id: UUID = Field(foreign_key="personal_goals.id", primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", primary_key=True)
    access_level: str = Field(default="READ") # READ, WRITE
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )


class PersonalGoalContribution(SQLModel, table=True):
    __tablename__: ClassVar[str] = "personal_goal_contributions"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    family_id: UUID = Field(foreign_key="families.id", index=True)
    goal_id: UUID = Field(foreign_key="personal_goals.id", index=True)
    user_id: UUID = Field(foreign_key="users.id")
    amount: Decimal = Field(default=0.0, max_digits=12, decimal_places=2)
    direction: str = Field(default="IN") # IN (saved toward goal), OUT (withdrawn)
    contribution_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    source_type: str = Field(default="MANUAL") # MANUAL, SCHEDULED
    source_id: Optional[UUID] = Field(default=None)
    document_id: Optional[UUID] = Field(default=None, foreign_key="documents.id")
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

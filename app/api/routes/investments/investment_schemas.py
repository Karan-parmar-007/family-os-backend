from typing import Literal, Optional, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from uuid import UUID


class SplitLineRequest(BaseModel):
    poolType: str
    amount: Decimal
    familyId: Optional[UUID] = None
    userId: Optional[UUID] = None
    expectedTotal: Optional[Decimal] = None
    obligationRemaining: Optional[Decimal] = None


class CreateInvestmentRequest(BaseModel):
    investmentName: str
    type: str
    inSomeoneName: Optional[str] = None
    initialLumpSum: Optional[Decimal] = None
    splitLines: Optional[List[SplitLineRequest]] = None
    
    returnType: Optional[str] = None
    annualReturnRate: Optional[Decimal] = None
    compoundingFrequency: Optional[str] = None
    
    hasRecurring: bool = False
    contributionAmount: Optional[Decimal] = None
    contributionEvery: Optional[str] = None
    nextContributionDate: Optional[datetime] = None
    
    tenureMonths: Optional[int] = None
    requiresConfirmation: bool = True
    maturityDate: Optional[datetime] = None
    maturityAmount: Optional[Decimal] = None
    autoCreditOnMaturity: bool = False
    
    documentId: Optional[UUID] = None
    accessLevel: str = "FAMILY"
    isPersonal: bool = False
    excludedUserIds: Optional[List[UUID]] = None
    selectedUserIds: Optional[List[UUID]] = None


class UpdateInvestmentRequest(BaseModel):
    investmentName: Optional[str] = None
    type: Optional[str] = None
    inSomeoneName: Optional[str] = None
    
    returnType: Optional[str] = None
    annualReturnRate: Optional[Decimal] = None
    compoundingFrequency: Optional[str] = None
    
    hasRecurring: Optional[bool] = None
    contributionAmount: Optional[Decimal] = None
    contributionEvery: Optional[str] = None
    nextContributionDate: Optional[datetime] = None
    
    tenureMonths: Optional[int] = None
    requiresConfirmation: Optional[bool] = None
    maturityDate: Optional[datetime] = None
    maturityAmount: Optional[Decimal] = None
    autoCreditOnMaturity: Optional[bool] = None
    
    documentId: Optional[UUID] = None
    accessLevel: Optional[str] = None


class ContributeToInvestmentRequest(BaseModel):
    amount: Decimal
    splitLines: Optional[List[SplitLineRequest]] = None
    mode: Literal["KEEP_SCHEDULE", "REDUCE_CONTRIBUTION", "REDUCE_TENURE"] = "KEEP_SCHEDULE"
    note: Optional[str] = None
    paidExternally: bool = False


class RedeemInvestmentRequest(BaseModel):
    amount: Decimal
    creditPool: Literal["FAMILY", "PERSONAL"] = "FAMILY"
    note: Optional[str] = None


class UpdateInvestmentValueRequest(BaseModel):
    currentValue: Decimal


class InvestmentSplitPlanRequest(BaseModel):
    splitLines: List[SplitLineRequest]
    showSplitToFamily: bool = True

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class InvestmentResponse(BaseModel):
    id: UUID
    family_id: UUID
    scope_type: str
    investment_name: str
    type: str
    status: str
    in_someone_name: Optional[UUID] = None
    is_personal: bool = False
    invested_amount: Decimal
    current_value: Decimal
    return_type: Optional[str] = None
    annual_return_rate: Optional[float] = None
    compounding_frequency: Optional[str] = None
    has_recurring: bool = False
    contribution_amount: Optional[Decimal] = None
    contribution_every: Optional[str] = None
    next_contribution_date: Optional[datetime] = None
    tenure_months: Optional[int] = None
    requires_confirmation: bool = True
    maturity_date: Optional[datetime] = None
    maturity_amount: Optional[Decimal] = None
    auto_credit_on_maturity: bool = True
    completed_at: Optional[datetime] = None
    document_id: Optional[UUID] = None
    access_level: str
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class InvestmentListResponse(BaseModel):
    items: List[InvestmentResponse]
    investedTotal: Decimal
    currentValueTotal: Decimal

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class InvestmentTxnResponse(BaseModel):
    id: UUID
    investment_id: UUID
    txn_type: str
    amount: Decimal
    direction: str
    occurred_at: datetime
    source_type: str
    note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class InvestmentTxnListResponse(BaseModel):
    items: List[InvestmentTxnResponse]

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


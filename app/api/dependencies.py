from app.auth.fos_profile import FosProfileDep as CurrentUserDep
# app/api/dependencies.py

from typing import Annotated
from fastapi import Depends


from app.api.db_dependencies import GarageClientDep, MongoDBDep, PGSessionDep
from app.api.routes.assets.assets_service import AssetsService
from app.api.routes.debt.debt_service import DebtService
from app.api.routes.document.document_service import DocumentService
from app.api.routes.expense.expense_service import ExpenseService
from app.api.routes.family.family_service import FamilyService
from app.api.routes.family_relationship.family_relationship_service import (
    FamilyRelationshipService,
)
from app.api.routes.family_expense.expense_service import RecurringExpenseService
from app.api.routes.family_income.income_service import IncomeService
from app.api.routes.health.health_service import HealthService
from app.api.routes.insurance.insurance_service import InsuranceService
from app.api.routes.savings.savings_service import SavingsService
from app.api.routes.notification.notification_service import NotificationService
from app.api.routes.scheduler.scheduler_service import SchedulerService
from app.api.routes.transfer.transfer_service import TransferService
from app.api.routes.friend.friend_service import FriendService
from app.api.routes.upcoming.upcoming_service import UpcomingService
from app.api.routes.user.user_service import UserService


async def get_health_service(
    session: PGSessionDep,
    mongo: MongoDBDep,
    garage_client: GarageClientDep,
) -> HealthService:
    return HealthService(
        pg_session=session,
        mongo_db=mongo,
        garage_client=garage_client,
    )




async def get_user_service(
    session: PGSessionDep,
) -> UserService:
    return UserService(pg_session=session)


async def get_family_service(
    session: PGSessionDep,
    mongo: MongoDBDep,
    garage_client: GarageClientDep,
) -> FamilyService:
    return FamilyService(
        pg_session=session,
        mongo_db=mongo,
        garage_client=garage_client,
    )


async def get_family_relationship_service(
    session: PGSessionDep,
) -> FamilyRelationshipService:
    return FamilyRelationshipService(pg_session=session)


async def get_income_service(
    session: PGSessionDep,
    garage_client: GarageClientDep,
) -> IncomeService:
    return IncomeService(pg_session=session, garage_client=garage_client)


async def get_document_service(
    session: PGSessionDep,
    garage_client: GarageClientDep,
) -> DocumentService:
    return DocumentService(pg_session=session, garage_client=garage_client)


async def get_debt_service(session: PGSessionDep) -> DebtService:
    return DebtService(pg_session=session)


async def get_savings_service(session: PGSessionDep) -> SavingsService:
    return SavingsService(pg_session=session)


async def get_assets_service(session: PGSessionDep) -> AssetsService:
    return AssetsService(pg_session=session)


async def get_recurring_expense_service(
    session: PGSessionDep,
    garage_client: GarageClientDep,
) -> RecurringExpenseService:
    return RecurringExpenseService(pg_session=session, garage_client=garage_client)


async def get_expense_service(session: PGSessionDep) -> ExpenseService:
    return ExpenseService(pg_session=session)


async def get_insurance_service(session: PGSessionDep) -> InsuranceService:
    return InsuranceService(pg_session=session)





async def get_transfer_service(session: PGSessionDep) -> TransferService:
    return TransferService(pg_session=session)


async def get_friend_service(session: PGSessionDep) -> FriendService:
    return FriendService(pg_session=session)


async def get_notification_service(session: PGSessionDep) -> NotificationService:
    return NotificationService(pg_session=session)


async def get_scheduler_service(session: PGSessionDep) -> SchedulerService:
    return SchedulerService(pg_session=session)


async def get_upcoming_service(session: PGSessionDep) -> UpcomingService:
    return UpcomingService(pg_session=session)


type HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
type UserServiceDep = Annotated[UserService, Depends(get_user_service)]
type FamilyServiceDep = Annotated[FamilyService, Depends(get_family_service)]
type FamilyRelationshipServiceDep = Annotated[
    FamilyRelationshipService, Depends(get_family_relationship_service)
]
type IncomeServiceDep = Annotated[IncomeService, Depends(get_income_service)]
type DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
type DebtServiceDep = Annotated[DebtService, Depends(get_debt_service)]
type SavingsServiceDep = Annotated[SavingsService, Depends(get_savings_service)]
type AssetsServiceDep = Annotated[AssetsService, Depends(get_assets_service)]
type RecurringExpenseServiceDep = Annotated[
    RecurringExpenseService, Depends(get_recurring_expense_service)
]
type ExpenseServiceDep = Annotated[ExpenseService, Depends(get_expense_service)]
type InsuranceServiceDep = Annotated[InsuranceService, Depends(get_insurance_service)]
type TransferServiceDep = Annotated[TransferService, Depends(get_transfer_service)]
type FriendServiceDep = Annotated[FriendService, Depends(get_friend_service)]
type NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]
type SchedulerServiceDep = Annotated[SchedulerService, Depends(get_scheduler_service)]
type UpcomingServiceDep = Annotated[UpcomingService, Depends(get_upcoming_service)]

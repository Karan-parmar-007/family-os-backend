import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.expense.model import FamilyExpenseLog
from app.api.routes.family.model import Family, SavingsLedger
from app.api.routes.family_income.model import FamilyIncomeLog, PersonalIncomeLog
from app.api.routes.family_relationship.family_relationship_service import (
    FamilyRelationshipService,
)
from app.api.routes.friend.friend_service import FriendService
from app.api.routes.scheduler.model import Notification
from app.api.routes.profile.model import FosProfile
from app.api.routes.transfer.model import Transfer
from app.api.routes.transfer.transfer_schemas import TransferCreateRequest, TransferUpdateRequest
from app.api.routes.user.model import UserBase, UserFamilyLink
from app.core.constants import (
    LEDGER_IN,
    LEDGER_OUT,
    LEDGER_SOURCE_TRANSFER,
    NOTIF_STATUS_UNREAD,
    TRANSFER_ENTITY_SAVINGS,
    TRANSFER_STATUS_ACTIVE,
    TRANSFER_STATUS_CANCELLED,
    TRANSFER_STATUS_COMPLETED,
    TRANSFER_STATUS_PENDING,
)
from app.core.date_advance import advance_next_date
from app.core.funding_service import InsufficientFundsError
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef
from app.core.transfer_pools import scope_to_pool
from app.scheduler.jobs import SOURCE_TRANSFER

logger = logging.getLogger(__name__)


class TransferService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def list_transfers(
        self, family_id: UUID
    ) -> list[tuple[Transfer, str]]:
        sent = list(
            (
                await self.pg_session.execute(
                    select(Transfer)
                    .where(Transfer.family_id == family_id)
                    .order_by(Transfer.created_at.desc())
                )
            ).scalars().all()
        )
        received = list(
            (
                await self.pg_session.execute(
                    select(Transfer)
                    .where(Transfer.to_family_id == family_id)
                    .order_by(Transfer.created_at.desc())
                )
            ).scalars().all()
        )
        rows: list[tuple[Transfer, str]] = [(t, "SENT") for t in sent]
        seen = {t.id for t in sent}
        for t in received:
            if t.id not in seen:
                rows.append((t, "RECEIVED"))
        rows.sort(key=lambda x: x[0].created_at, reverse=True)
        return rows

    async def list_personal_transfers(
        self, user_id: UUID
    ) -> list[tuple[Transfer, str]]:
        stmt = (
            select(Transfer)
            .where(
                or_(
                    Transfer.from_user_id == user_id,
                    Transfer.to_user_id == user_id,
                    Transfer.created_by == user_id,
                ),
                or_(
                    Transfer.from_scope == "PERSONAL",
                    Transfer.to_scope == "PERSONAL",
                ),
            )
            .order_by(Transfer.created_at.desc())
        )
        transfers = list((await self.pg_session.execute(stmt)).scalars().all())
        rows: list[tuple[Transfer, str]] = []
        for t in transfers:
            if t.from_user_id == user_id or (
                t.from_scope == "PERSONAL" and t.created_by == user_id
            ):
                rows.append((t, "SENT"))
            else:
                rows.append((t, "RECEIVED"))
        return rows

    async def get_transfer(
        self, transfer_id: UUID, family_id: UUID
    ) -> Transfer | None:
        stmt = select(Transfer).where(
            Transfer.id == transfer_id,
            or_(Transfer.family_id == family_id, Transfer.to_family_id == family_id),
        )
        return (await self.pg_session.execute(stmt)).scalar_one_or_none()

    async def get_personal_transfer(
        self, transfer_id: UUID, user_id: UUID
    ) -> Transfer | None:
        stmt = select(Transfer).where(
            Transfer.id == transfer_id,
            or_(
                Transfer.from_user_id == user_id,
                Transfer.to_user_id == user_id,
                Transfer.created_by == user_id,
            ),
        )
        return (await self.pg_session.execute(stmt)).scalar_one_or_none()

    async def get_transfer_ledger(self, transfer_id: UUID) -> list[SavingsLedger]:
        stmt = (
            select(SavingsLedger)
            .where(
                SavingsLedger.source_type == LEDGER_SOURCE_TRANSFER,
                SavingsLedger.source_id == transfer_id,
            )
            .order_by(SavingsLedger.occurred_at.asc())
        )
        return list((await self.pg_session.execute(stmt)).scalars().all())

    async def _assert_member(self, user_id: UUID, family_id: UUID) -> None:
        stmt = select(UserFamilyLink.user_id).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id == family_id,
        )
        row = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise PermissionError("User is not a member of this family")

    async def _is_member(self, user_id: UUID, family_id: UUID) -> bool:
        stmt = select(UserFamilyLink.user_id).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id == family_id,
        )
        row = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        return row is not None

    async def _validate_and_gate(
        self,
        *,
        created_by: UUID,
        family_id: UUID | None,
        request: TransferCreateRequest,
        from_scope: str,
        to_scope: str,
        from_user_id: UUID | None,
        to_user_id: UUID | None,
        to_family_id: UUID | None,
    ) -> None:
        friend_service = FriendService(self.pg_session)

        if from_scope == "FAMILY" and to_scope == "FAMILY":
            if family_id is None or to_family_id is None:
                raise ValueError("family_id and to_family_id are required for FAMILY→FAMILY")
            if to_family_id == family_id:
                raise ValueError("Cannot transfer to the same family")
            # Scenario 2: Non-connected family via link code
            if getattr(request, "dest_link_code", None):
                return
            # Scenario 1: Connected family via active relationship
            relationship_service = FamilyRelationshipService(self.pg_session)
            await relationship_service.require_active_relationship(
                family_a_id=family_id,
                family_b_id=to_family_id,
            )
            return

        if from_scope == "FAMILY" and to_scope == "PERSONAL":
            if family_id is None or to_user_id is None:
                raise ValueError("family_id and to_user_id are required for FAMILY→PERSONAL")
            # Scenario 4: Family to other personal account via his personal code
            if getattr(request, "dest_personal_code", None):
                return
            # Scenario 3: Family to a family member personal account
            is_mem = await self._is_member(to_user_id, family_id)
            if not is_mem:
                raise PermissionError("Recipient must be an active member of this family or specified via personal code")
            return

        if from_scope == "PERSONAL" and to_scope == "FAMILY":
            if to_family_id is None:
                raise ValueError("to_family_id is required for PERSONAL→FAMILY")
            # Scenario 4: Personal to family via family code (where user is not part of that family)
            if getattr(request, "dest_link_code", None):
                return
            # Scenario 1: Personal to family (where person is a member of that family)
            actor = from_user_id or created_by
            await self._assert_member(actor, to_family_id)
            return

        if from_scope == "PERSONAL" and to_scope == "PERSONAL":
            if to_user_id is None:
                raise ValueError("to_user_id is required for PERSONAL→PERSONAL")
            actor = from_user_id or created_by
            if actor == to_user_id:
                raise ValueError("Cannot transfer to yourself")
            # Scenario 3: Person to person via personal code
            if getattr(request, "dest_personal_code", None):
                return
            # Scenario 2: Person to person as friends connected
            await friend_service.assert_active_friends(actor, to_user_id)
            return

        raise ValueError(f"Unsupported transfer scopes: {from_scope}→{to_scope}")

    async def create_transfer(
        self,
        family_id: UUID | None,
        created_by: UUID,
        request: TransferCreateRequest,
    ) -> Transfer:
        from_scope = request.from_scope or "FAMILY"
        to_scope = request.to_scope or "FAMILY"
        from_user_id = request.from_user_id
        to_user_id = request.to_user_id
        to_family_id = request.to_family_id

        if request.dest_link_code and to_family_id is None:
            code = request.dest_link_code.strip()
            fam = (
                await self.pg_session.execute(
                    select(Family).where(
                        or_(Family.link_code == code, Family.membership_code == code)
                    )
                )
            ).scalars().first()
            if fam is None:
                raise ValueError("Unknown family link code")
            to_family_id = fam.id
            request.to_family_id = fam.id

        if request.dest_personal_code and to_user_id is None:
            code = request.dest_personal_code.strip()
            profile = (
                await self.pg_session.execute(
                    select(FosProfile).where(FosProfile.personal_code == code)
                )
            ).scalars().first()
            if profile is None:
                raise ValueError("Unknown personal code")
            to_user_id = profile.id
            request.to_user_id = profile.id

        if from_scope == "PERSONAL":
            from_user_id = from_user_id or created_by
        if to_scope == "PERSONAL" and to_user_id is None:
            raise ValueError("to_user_id is required when to_scope is PERSONAL")
        if to_scope == "FAMILY" and to_family_id is None:
            raise ValueError("to_family_id is required when to_scope is FAMILY")

        await self._validate_and_gate(
            created_by=created_by,
            family_id=family_id,
            request=request,
            from_scope=from_scope,
            to_scope=to_scope,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            to_family_id=to_family_id,
        )

        status = TRANSFER_STATUS_ACTIVE if request.is_recurring else TRANSFER_STATUS_PENDING

        transfer = Transfer(
            family_id=family_id,
            to_family_id=to_family_id,
            from_scope=from_scope,
            to_scope=to_scope,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            entity_type=request.entity_type or TRANSFER_ENTITY_SAVINGS,
            amount=request.amount,
            note=request.note,
            is_recurring=request.is_recurring,
            recurring_every=request.recurring_every,
            next_run_date=request.next_run_date,
            end_date=request.end_date,
            requires_confirmation=True,
            show_breakdown_to_receiver=request.show_breakdown_to_receiver,
            status=status,
            created_by=created_by,
        )
        self.pg_session.add(transfer)
        await self.pg_session.flush()
        await self.pg_session.commit()
        await self.pg_session.refresh(transfer)
        return transfer

    async def accept_transfer(self, transfer: Transfer, actor_id: UUID) -> Transfer:
        if transfer.status not in {TRANSFER_STATUS_PENDING}:
            raise ValueError("Only pending offers can be accepted")
        if transfer.created_by == actor_id:
            raise PermissionError("Sender cannot accept their own offer")

        if transfer.to_scope == "PERSONAL":
            if transfer.to_user_id != actor_id:
                raise PermissionError("Only the destination person can accept this offer")
        elif transfer.to_scope == "FAMILY" and transfer.to_family_id is not None:
            stmt = select(UserFamilyLink).where(
                UserFamilyLink.user_id == actor_id,
                UserFamilyLink.family_id == transfer.to_family_id,
                UserFamilyLink.is_family_manager.is_(True),
            )
            head = (await self.pg_session.execute(stmt)).scalars().first()
            if head is None:
                raise PermissionError("Only the destination family head can accept this offer")

        try:
            await self.execute_transfer_run(transfer)
        except InsufficientFundsError:
            await self.pg_session.rollback()
            raise
        transfer.status = TRANSFER_STATUS_COMPLETED
        await self.pg_session.commit()
        await self.pg_session.refresh(transfer)
        return transfer

    async def decline_transfer(self, transfer: Transfer, actor_id: UUID) -> Transfer:
        if transfer.status != TRANSFER_STATUS_PENDING:
            raise ValueError("Only pending offers can be declined")
        if transfer.created_by == actor_id:
            raise PermissionError("Sender cannot decline their own offer")
        transfer.status = TRANSFER_STATUS_CANCELLED
        await self.pg_session.commit()
        await self.pg_session.refresh(transfer)
        return transfer

    async def create_personal_transfer(
        self,
        created_by: UUID,
        request: TransferCreateRequest,
    ) -> Transfer:
        """User-scoped create: PERSONAL→PERSONAL or PERSONAL→FAMILY."""
        request.from_scope = "PERSONAL"
        request.from_user_id = created_by
        if request.to_scope not in {"PERSONAL", "FAMILY"}:
            raise ValueError("Personal transfers must go to PERSONAL or FAMILY")
        family_id = None
        if request.to_scope == "FAMILY":
            family_id = None  # origin is personal
        return await self.create_transfer(family_id, created_by, request)

    async def update_transfer(
        self, transfer: Transfer, request: TransferUpdateRequest
    ) -> Transfer:
        for field, value in request.model_dump(exclude_none=True).items():
            setattr(transfer, field, value)
        if transfer.is_recurring and transfer.next_run_date:
            from app.scheduler.transfer_cron import create_or_replace_next_transfer_job

            await create_or_replace_next_transfer_job(self.pg_session, transfer)
        await self.pg_session.commit()
        await self.pg_session.refresh(transfer)
        return transfer

    def _resolve_pools(self, transfer: Transfer) -> tuple[SavingsPoolRef, SavingsPoolRef]:
        sender_pool = scope_to_pool(
            transfer.from_scope,
            family_id=transfer.family_id,
            user_id=transfer.from_user_id or transfer.created_by,
        )
        receiver_pool = scope_to_pool(
            transfer.to_scope,
            family_id=transfer.to_family_id,
            user_id=transfer.to_user_id,
        )
        return sender_pool, receiver_pool

    async def execute_transfer_run(self, transfer: Transfer) -> None:
        """Apply one transfer run: dual ledger + optional expense/income logs."""
        # Re-validate gates for scheduled runs
        await self._validate_and_gate(
            created_by=transfer.created_by,
            family_id=transfer.family_id,
            request=TransferCreateRequest(
                to_family_id=transfer.to_family_id,
                to_user_id=transfer.to_user_id,
                from_scope=transfer.from_scope,
                to_scope=transfer.to_scope,
                from_user_id=transfer.from_user_id,
                amount=transfer.amount,
            ),
            from_scope=transfer.from_scope,
            to_scope=transfer.to_scope,
            from_user_id=transfer.from_user_id,
            to_user_id=transfer.to_user_id,
            to_family_id=transfer.to_family_id,
        )

        sender_pool, receiver_pool = self._resolve_pools(transfer)
        ledger = SavingsLedgerService(self.pg_session)

        source_row = await ledger._get_or_create_pool_row(sender_pool)
        if source_row.total_savings < transfer.amount:
            raise InsufficientFundsError(
                sender_pool.pool_type,
                sender_pool.family_id or sender_pool.user_id,
                source_row.total_savings,
                transfer.amount,
            )

        sender_label = await self._pool_label(transfer.from_scope, transfer.family_id, transfer.from_user_id)
        receiver_label = await self._pool_label(
            transfer.to_scope, transfer.to_family_id, transfer.to_user_id
        )

        when = datetime.now(timezone.utc)
        await ledger.apply_movement(
            sender_pool,
            transfer.amount,
            LEDGER_OUT,
            LEDGER_SOURCE_TRANSFER,
            source_id=transfer.id,
            occurred_at=when,
        )
        await ledger.apply_movement(
            receiver_pool,
            transfer.amount,
            LEDGER_IN,
            LEDGER_SOURCE_TRANSFER,
            source_id=transfer.id,
            occurred_at=when,
        )

        # Artifact logs for family endpoints
        if transfer.from_scope == "FAMILY" and transfer.family_id is not None:
            expense_log = FamilyExpenseLog(
                family_id=transfer.family_id,
                scope_type="FAMILY",
                logged_by=transfer.created_by,
                expense_name=f"Transfer to {receiver_label}",
                amount=transfer.amount,
                expense_date=when,
                source_type="TRANSFER",
                source_id=transfer.id,
            )
            self.pg_session.add(expense_log)

        if transfer.to_scope == "FAMILY" and transfer.to_family_id is not None:
            income_label = (
                f"Transfer from {sender_label}"
                if transfer.show_breakdown_to_receiver
                else "External transfer"
            )
            income_log = FamilyIncomeLog(
                family_id=transfer.to_family_id,
                scope_type="FAMILY",
                logged_by=transfer.created_by,
                income_name=income_label,
                total_amount=transfer.amount,
                family_amount=transfer.amount,
                income_date=when,
                source_type="TRANSFER",
                source_id=transfer.id,
                added_by_user_id=transfer.created_by,
            )
            self.pg_session.add(income_log)

        if transfer.to_scope == "PERSONAL" and transfer.to_user_id is not None:
            income_label = (
                f"Transfer from {sender_label}"
                if transfer.show_breakdown_to_receiver
                else "External transfer"
            )
            personal_log = PersonalIncomeLog(
                family_id=transfer.family_id or transfer.to_family_id,
                user_id=transfer.to_user_id,
                logged_by=transfer.created_by,
                income_name=income_label,
                amount=transfer.amount,
                income_date=when,
                source_type="TRANSFER",
                source_id=transfer.id,
            )
            self.pg_session.add(personal_log)

        if transfer.is_recurring and transfer.next_run_date is not None:
            transfer.next_run_date = advance_next_date(
                transfer.next_run_date,
                every=transfer.recurring_every or "MONTHLY",
            )
            if transfer.end_date and transfer.next_run_date > transfer.end_date:
                transfer.status = TRANSFER_STATUS_COMPLETED
                transfer.is_recurring = False
            else:
                from app.scheduler.transfer_cron import create_or_replace_next_transfer_job

                await create_or_replace_next_transfer_job(self.pg_session, transfer)
        else:
            transfer.status = TRANSFER_STATUS_COMPLETED

        notify_user_id = transfer.to_user_id or transfer.created_by
        self.pg_session.add(
            Notification(
                user_id=notify_user_id,
                family_id=transfer.to_family_id or transfer.family_id,
                type="TRANSFER_RECEIVED",
                title=f"Received {transfer.amount}",
                body=f"Transfer from {sender_label}",
                related_entity_type=SOURCE_TRANSFER,
                related_entity_id=transfer.id,
                allowed_actions={"actions": ["DISMISS"]},
                status=NOTIF_STATUS_UNREAD,
            )
        )
        await self.pg_session.flush()

    async def _pool_label(
        self,
        scope: str,
        family_id: UUID | None,
        user_id: UUID | None,
    ) -> str:
        if scope == "FAMILY" and family_id is not None:
            family = await self.pg_session.get(Family, family_id)
            return family.name if family else "Family"
        if user_id is not None:
            user = await self.pg_session.get(UserBase, user_id)
            return user.name if user else "Personal"
        return "Personal"

    async def _apply_savings_transfer(self, transfer: Transfer) -> None:
        """Backward-compatible entry used by scheduler jobs."""
        await self.execute_transfer_run(transfer)

    async def cancel_transfer(
        self,
        transfer: Transfer,
        user_id: UUID,
        *,
        is_manager: bool,
    ) -> Transfer:
        if transfer.created_by != user_id and not is_manager:
            raise PermissionError("Only the initiator or a family manager may cancel")
        if transfer.status == TRANSFER_STATUS_CANCELLED:
            raise ValueError("Transfer already cancelled")

        from sqlalchemy import update
        from app.api.routes.scheduler.model import ScheduledJob
        from app.core.constants import JOB_STATUS_CANCELLED, JOB_TYPE_AUTO_TRANSFER

        transfer.status = TRANSFER_STATUS_CANCELLED
        transfer.is_recurring = False
        await self.pg_session.execute(
            update(ScheduledJob)
            .where(
                ScheduledJob.source_type == SOURCE_TRANSFER,
                ScheduledJob.source_id == transfer.id,
                ScheduledJob.job_type == JOB_TYPE_AUTO_TRANSFER,
            )
            .values(status=JOB_STATUS_CANCELLED)
        )
        await self.pg_session.commit()
        await self.pg_session.refresh(transfer)
        return transfer

    async def reverse_transfer(
        self,
        transfer: Transfer,
        user_id: UUID,
        *,
        is_manager: bool,
    ) -> Transfer:
        if transfer.status != TRANSFER_STATUS_COMPLETED:
            raise ValueError("Only completed transfers can be reversed")
        if transfer.created_by != user_id and not is_manager:
            raise PermissionError("Only the initiator or a family manager may reverse")

        # Swap scopes/endpoints
        reverse_req = TransferCreateRequest(
            to_family_id=transfer.family_id,
            to_user_id=transfer.from_user_id,
            from_scope=transfer.to_scope,
            to_scope=transfer.from_scope,
            from_user_id=transfer.to_user_id,
            amount=transfer.amount,
            note=f"Reversal of transfer {transfer.id}",
            show_breakdown_to_receiver=transfer.show_breakdown_to_receiver,
            requires_confirmation=False,
        )
        source_family_id = transfer.to_family_id if transfer.to_scope == "FAMILY" else transfer.family_id
        return await self.create_transfer(source_family_id, user_id, reverse_req)

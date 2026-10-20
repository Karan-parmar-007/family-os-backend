"""Transfers between family and personal savings pools.

Destinations:
- FAMILY→FAMILY: connected families are instant; any other family by link code.
- FAMILY→PERSONAL: members of the sending family are instant; anyone by personal code.
- PERSONAL→PERSONAL: friends are instant; anyone by personal code.
- PERSONAL→FAMILY: families you belong to are instant; any other family by link code.

A code that resolves to a direct destination is instant too. Everything else
waits for the receiver (the person, or any member of the receiving family) to
accept. Any member may send from a family. Money only moves inside
``execute_transfer_run``, which locks both pools in a fixed order.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.family.model import Family, FamilyRelationship, SavingsLedger
from app.api.routes.friend.friend_service import FriendService
from app.api.routes.profile.model import FosProfile
from app.api.routes.scheduler.model import Notification
from app.api.routes.transfer.model import Transfer
from app.api.routes.transfer.transfer_schemas import TransferCreateRequest, TransferUpdateRequest
from app.api.routes.user.model import UserFamilyLink
from app.api.schemas.pagination import PaginationParams
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
from app.core.date_advance import normalize_frequency
from app.core.funding_service import InsufficientFundsError
from app.core.savings_ledger_service import SavingsLedgerService, SavingsPoolRef
from app.core.transfer_pools import scope_to_pool

logger = logging.getLogger(__name__)

TRANSFER_STATUS_FAILED = "FAILED"
RELATIONSHIP_ACTIVE = "ACTIVE"


class CodeNotFoundError(Exception):
    pass


def _clean_code(raw: str | None) -> str:
    return "".join((raw or "").split()).upper()


class TransferService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    # --- lookups ---

    async def _membership(self, user_id: UUID, family_id: UUID | None) -> UserFamilyLink | None:
        if family_id is None:
            return None
        stmt = select(UserFamilyLink).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id == family_id,
        )
        return (await self.pg_session.execute(stmt)).scalars().first()

    async def _is_member(self, user_id: UUID, family_id: UUID | None) -> bool:
        return await self._membership(user_id, family_id) is not None

    async def _family_member_ids(self, family_id: UUID) -> list[UUID]:
        stmt = select(UserFamilyLink.user_id).where(UserFamilyLink.family_id == family_id)
        return list((await self.pg_session.execute(stmt)).scalars().all())

    async def _connected(self, family_a: UUID, family_b: UUID) -> bool:
        stmt = select(FamilyRelationship.id).where(
            FamilyRelationship.status == RELATIONSHIP_ACTIVE,
            or_(
                and_(FamilyRelationship.family_a_id == family_a, FamilyRelationship.family_b_id == family_b),
                and_(FamilyRelationship.family_a_id == family_b, FamilyRelationship.family_b_id == family_a),
            ),
        )
        return (await self.pg_session.execute(stmt)).first() is not None

    async def family_by_code(self, code: str | None) -> Family | None:
        code = _clean_code(code)
        if not code:
            return None
        stmt = select(Family).where(or_(Family.link_code == code, Family.join_code == code))
        return (await self.pg_session.execute(stmt)).scalars().first()

    async def profile_by_code(self, code: str | None) -> FosProfile | None:
        code = _clean_code(code)
        if not code:
            return None
        stmt = select(FosProfile).where(FosProfile.personal_code == code)
        return (await self.pg_session.execute(stmt)).scalars().first()

    async def _is_direct(
        self,
        *,
        actor_id: UUID,
        from_scope: str,
        family_id: UUID | None,
        to_scope: str,
        to_family_id: UUID | None,
        to_user_id: UUID | None,
    ) -> bool:
        if from_scope == "FAMILY" and to_scope == "FAMILY":
            return await self._connected(family_id, to_family_id)
        if from_scope == "FAMILY" and to_scope == "PERSONAL":
            return await self._is_member(to_user_id, family_id)
        if from_scope == "PERSONAL" and to_scope == "FAMILY":
            return await self._is_member(actor_id, to_family_id)
        return await FriendService(self.pg_session).are_active_friends(actor_id, to_user_id)

    async def lookup_code(
        self,
        actor_id: UUID,
        code: str,
        *,
        from_scope: str,
        family_id: UUID | None,
    ) -> dict:
        from_scope = (from_scope or "PERSONAL").upper()
        if from_scope == "FAMILY" and not await self._is_member(actor_id, family_id):
            raise PermissionError("You are not a member of this family")
        fam = await self.family_by_code(code)
        if fam is not None:
            if from_scope == "FAMILY" and fam.id == family_id:
                raise ValueError("That is this family's own code")
            instant = await self._is_direct(
                actor_id=actor_id, from_scope=from_scope, family_id=family_id,
                to_scope="FAMILY", to_family_id=fam.id, to_user_id=None,
            )
            return {"kind": "FAMILY", "id": fam.id, "name": fam.name, "instant": instant}
        profile = await self.profile_by_code(code)
        if profile is not None:
            if from_scope == "PERSONAL" and profile.id == actor_id:
                raise ValueError("That is your own code")
            instant = await self._is_direct(
                actor_id=actor_id, from_scope=from_scope, family_id=family_id,
                to_scope="PERSONAL", to_family_id=None, to_user_id=profile.id,
            )
            return {"kind": "PERSON", "id": profile.id, "name": profile.display_name, "instant": instant}
        raise CodeNotFoundError("No family or person has this code")

    # --- reads ---

    async def list_transfers(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        status: str | None = None,
    ) -> tuple[list[tuple[Transfer, str]], int]:
        sent = and_(Transfer.from_scope == "FAMILY", Transfer.family_id == family_id)
        received = and_(Transfer.to_scope == "FAMILY", Transfer.to_family_id == family_id)
        filters = [or_(sent, received)]
        if status:
            filters.append(Transfer.status == status.upper())
        return await self._page(filters, pagination, is_sent=lambda t: t.from_scope == "FAMILY" and t.family_id == family_id)

    async def list_personal_transfers(
        self,
        user_id: UUID,
        pagination: PaginationParams,
        *,
        status: str | None = None,
    ) -> tuple[list[tuple[Transfer, str]], int]:
        sent = and_(Transfer.from_scope == "PERSONAL", Transfer.from_user_id == user_id)
        received = and_(Transfer.to_scope == "PERSONAL", Transfer.to_user_id == user_id)
        filters = [or_(sent, received)]
        if status:
            filters.append(Transfer.status == status.upper())
        return await self._page(filters, pagination, is_sent=lambda t: t.from_scope == "PERSONAL" and t.from_user_id == user_id)

    async def _page(self, filters, pagination: PaginationParams, *, is_sent) -> tuple[list[tuple[Transfer, str]], int]:
        total = (
            await self.pg_session.execute(select(func.count()).select_from(Transfer).where(*filters))
        ).scalar_one()
        rows = (
            await self.pg_session.execute(
                select(Transfer)
                .where(*filters)
                .order_by(Transfer.created_at.desc(), Transfer.id.desc())
                .offset(pagination.offset)
                .limit(pagination.page_size)
            )
        ).scalars().all()
        return [(t, "SENT" if is_sent(t) else "RECEIVED") for t in rows], total

    async def get_transfer(self, transfer_id: UUID, family_id: UUID) -> Transfer | None:
        stmt = select(Transfer).where(
            Transfer.id == transfer_id,
            or_(
                and_(Transfer.from_scope == "FAMILY", Transfer.family_id == family_id),
                and_(Transfer.to_scope == "FAMILY", Transfer.to_family_id == family_id),
            ),
        )
        return (await self.pg_session.execute(stmt)).scalar_one_or_none()

    async def get_personal_transfer(self, transfer_id: UUID, user_id: UUID) -> Transfer | None:
        stmt = select(Transfer).where(
            Transfer.id == transfer_id,
            or_(
                and_(Transfer.from_scope == "PERSONAL", Transfer.from_user_id == user_id),
                and_(Transfer.to_scope == "PERSONAL", Transfer.to_user_id == user_id),
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

    async def labels(self, transfers: list[Transfer]) -> dict[tuple[str, UUID], str]:
        fam_ids = {t.family_id for t in transfers if t.from_scope == "FAMILY" and t.family_id}
        fam_ids |= {t.to_family_id for t in transfers if t.to_scope == "FAMILY" and t.to_family_id}
        user_ids = {t.from_user_id for t in transfers if t.from_scope == "PERSONAL" and t.from_user_id}
        user_ids |= {t.to_user_id for t in transfers if t.to_scope == "PERSONAL" and t.to_user_id}
        out: dict[tuple[str, UUID], str] = {}
        if fam_ids:
            for fid, name in (await self.pg_session.execute(select(Family.id, Family.name).where(Family.id.in_(fam_ids)))).all():
                out[("FAMILY", fid)] = name
        if user_ids:
            stmt = select(FosProfile.id, FosProfile.display_name).where(FosProfile.id.in_(user_ids))
            for uid, name in (await self.pg_session.execute(stmt)).all():
                out[("PERSONAL", uid)] = name
        return out

    @staticmethod
    def endpoint_label(labels: dict, scope: str, family_id: UUID | None, user_id: UUID | None) -> str:
        if scope == "FAMILY":
            return labels.get(("FAMILY", family_id), "Family")
        return labels.get(("PERSONAL", user_id), "Personal")

    # --- permissions ---

    async def can_accept(self, transfer: Transfer, actor_id: UUID) -> bool:
        if transfer.status != TRANSFER_STATUS_PENDING:
            return False
        if transfer.to_scope == "PERSONAL":
            return transfer.to_user_id == actor_id
        return await self._is_member(actor_id, transfer.to_family_id)

    async def can_cancel(self, transfer: Transfer, actor_id: UUID) -> bool:
        if transfer.status not in {TRANSFER_STATUS_PENDING, TRANSFER_STATUS_ACTIVE}:
            return False
        if transfer.created_by == actor_id:
            return True
        if transfer.from_scope == "FAMILY":
            link = await self._membership(actor_id, transfer.family_id)
            return bool(link and link.is_family_manager)
        return transfer.from_user_id == actor_id

    # --- writes ---

    async def _resolve_destination(
        self, actor_id: UUID, family_id: UUID | None, request: TransferCreateRequest
    ) -> tuple[UUID | None, UUID | None, bool]:
        """Returns (to_family_id, to_user_id, via_code)."""
        from_scope, to_scope = request.from_scope, request.to_scope
        to_family_id, to_user_id = request.to_family_id, request.to_user_id
        from_code = False

        if to_scope == "FAMILY":
            if to_family_id is None:
                fam = await self.family_by_code(request.dest_link_code)
                if fam is None:
                    raise ValueError("No family has this link code")
                to_family_id, from_code = fam.id, True
            elif await self.pg_session.get(Family, to_family_id) is None:
                raise ValueError("Family not found")
            if from_scope == "FAMILY" and to_family_id == family_id:
                raise ValueError("Pick a different family")
        else:
            if to_user_id is None:
                profile = await self.profile_by_code(request.dest_personal_code)
                if profile is None:
                    raise ValueError("No one has this personal code")
                to_user_id, from_code = profile.id, True
            elif await self.pg_session.get(FosProfile, to_user_id) is None:
                raise ValueError("Person not found")
            if from_scope == "PERSONAL" and to_user_id == actor_id:
                raise ValueError("You can't send money to yourself")

        direct = await self._is_direct(
            actor_id=actor_id, from_scope=from_scope, family_id=family_id,
            to_scope=to_scope, to_family_id=to_family_id, to_user_id=to_user_id,
        )
        if not direct and not from_code:
            if to_scope == "FAMILY":
                raise PermissionError("This family isn't connected; use their link code")
            raise PermissionError("This person isn't a member or friend; use their personal code")
        return to_family_id, to_user_id, not direct

    async def _existing_by_key(self, actor_id: UUID, key: str | None) -> Transfer | None:
        if not key:
            return None
        stmt = select(Transfer).where(Transfer.created_by == actor_id, Transfer.idempotency_key == key)
        return (await self.pg_session.execute(stmt)).scalars().first()

    async def create_transfer(
        self,
        family_id: UUID | None,
        created_by: UUID,
        request: TransferCreateRequest,
    ) -> Transfer:
        existing = await self._existing_by_key(created_by, request.idempotency_key)
        if existing is not None:
            return existing

        if request.from_scope == "FAMILY":
            if family_id is None:
                raise ValueError("Pick the family to send from")
            if not await self._is_member(created_by, family_id):
                raise PermissionError("You are not a member of this family")
            from_user_id = None
        else:
            family_id = None
            from_user_id = created_by

        to_family_id, to_user_id, via_code = await self._resolve_destination(created_by, family_id, request)
        recurring_every = normalize_frequency(request.recurring_every) if request.is_recurring else None
        if request.is_recurring and request.end_date and request.end_date < request.next_run_date:
            raise ValueError("End date must be after the first date")

        transfer = Transfer(
            family_id=family_id,
            to_family_id=to_family_id if request.to_scope == "FAMILY" else None,
            from_scope=request.from_scope,
            to_scope=request.to_scope,
            from_user_id=from_user_id,
            to_user_id=to_user_id if request.to_scope == "PERSONAL" else None,
            entity_type=request.entity_type or TRANSFER_ENTITY_SAVINGS,
            amount=request.amount,
            note=(request.note or "").strip() or None,
            is_recurring=request.is_recurring,
            recurring_every=recurring_every,
            next_run_date=request.next_run_date if request.is_recurring else None,
            end_date=request.end_date if request.is_recurring else None,
            requires_confirmation=via_code,
            via_code=via_code,
            show_breakdown_to_receiver=request.show_breakdown_to_receiver,
            idempotency_key=request.idempotency_key,
            status=TRANSFER_STATUS_ACTIVE if request.is_recurring else TRANSFER_STATUS_PENDING,
            created_by=created_by,
        )
        self.pg_session.add(transfer)
        try:
            await self.pg_session.flush()
        except IntegrityError:
            await self.pg_session.rollback()
            existing = await self._existing_by_key(created_by, request.idempotency_key)
            if existing is not None:
                return existing
            raise

        if not request.is_recurring:
            if via_code:
                await self._notify_offer(transfer)
            else:
                await self.execute_transfer_run(transfer)
        await self.pg_session.commit()
        await self.pg_session.refresh(transfer)
        return transfer

    async def create_personal_transfer(self, created_by: UUID, request: TransferCreateRequest) -> Transfer:
        request.from_scope = "PERSONAL"
        return await self.create_transfer(None, created_by, request)

    async def accept_transfer(self, transfer: Transfer, actor_id: UUID) -> Transfer:
        locked = await self.pg_session.get(Transfer, transfer.id, with_for_update=True, populate_existing=True)
        if locked is None or locked.status != TRANSFER_STATUS_PENDING:
            raise ValueError("This transfer is no longer waiting for you")
        if not await self.can_accept(locked, actor_id):
            raise PermissionError("Only the receiver can accept this transfer")
        try:
            await self.execute_transfer_run(locked)
        except InsufficientFundsError:
            await self.pg_session.rollback()
            raise
        await self.pg_session.commit()
        await self.pg_session.refresh(locked)
        return locked

    async def decline_transfer(self, transfer: Transfer, actor_id: UUID) -> Transfer:
        if not await self.can_accept(transfer, actor_id):
            raise PermissionError("Only the receiver can decline this transfer")
        transfer.status = TRANSFER_STATUS_CANCELLED
        transfer.failure_reason = "Declined by receiver"
        await self.pg_session.commit()
        await self.pg_session.refresh(transfer)
        return transfer

    async def cancel_transfer(self, transfer: Transfer, user_id: UUID) -> Transfer:
        if not await self.can_cancel(transfer, user_id):
            raise PermissionError("Only the sender or a head of the sending family can cancel")
        transfer.status = TRANSFER_STATUS_CANCELLED
        transfer.failure_reason = "Cancelled by sender"
        if transfer.is_recurring:
            transfer.next_run_date = None
        await self.pg_session.commit()
        await self.pg_session.refresh(transfer)
        return transfer

    async def update_transfer(self, transfer: Transfer, actor_id: UUID, request: TransferUpdateRequest) -> Transfer:
        if not transfer.is_recurring or transfer.status != TRANSFER_STATUS_ACTIVE:
            raise ValueError("Only active recurring transfers can be edited")
        if not await self.can_cancel(transfer, actor_id):
            raise PermissionError("Only the sender or a head of the sending family can edit")
        data = request.model_dump(exclude_unset=True)
        if "recurring_every" in data and data["recurring_every"]:
            data["recurring_every"] = normalize_frequency(data["recurring_every"])
        for field, value in data.items():
            if value is None and field in {"amount", "recurring_every", "next_run_date"}:
                continue
            setattr(transfer, field, value)
        await self.pg_session.commit()
        await self.pg_session.refresh(transfer)
        return transfer

    def _resolve_pools(self, transfer: Transfer) -> tuple[SavingsPoolRef, SavingsPoolRef]:
        sender = scope_to_pool(transfer.from_scope, family_id=transfer.family_id, user_id=transfer.from_user_id)
        receiver = scope_to_pool(transfer.to_scope, family_id=transfer.to_family_id, user_id=transfer.to_user_id)
        return sender, receiver

    async def execute_transfer_run(self, transfer: Transfer) -> None:
        """Move the money for one transfer. Caller commits."""
        sender_pool, receiver_pool = self._resolve_pools(transfer)
        ledger = SavingsLedgerService(self.pg_session)
        await ledger.lock_pools([sender_pool, receiver_pool])
        available = await ledger.balance(sender_pool, lock=True)
        if available < transfer.amount:
            raise InsufficientFundsError(
                sender_pool.pool_type,
                sender_pool.family_id or sender_pool.user_id,
                available,
                transfer.amount,
            )

        labels = await self.labels([transfer])
        sender_label = self.endpoint_label(labels, transfer.from_scope, transfer.family_id, transfer.from_user_id)
        receiver_label = self.endpoint_label(labels, transfer.to_scope, transfer.to_family_id, transfer.to_user_id)
        when = datetime.now(timezone.utc)
        await ledger.apply_movement(
            sender_pool, transfer.amount, LEDGER_OUT, LEDGER_SOURCE_TRANSFER,
            source_id=transfer.id, description=f"Transfer to {receiver_label}", occurred_at=when,
        )
        shown_sender = sender_label if transfer.show_breakdown_to_receiver else "another account"
        await ledger.apply_movement(
            receiver_pool, transfer.amount, LEDGER_IN, LEDGER_SOURCE_TRANSFER,
            source_id=transfer.id, description=f"Transfer from {shown_sender}", occurred_at=when,
        )
        transfer.status = TRANSFER_STATUS_COMPLETED
        transfer.completed_at = when
        await self._notify(
            transfer,
            await self._receiver_ids(transfer),
            type_="TRANSFER_RECEIVED",
            title=f"Received {transfer.amount}",
            body=f"Transfer from {shown_sender}",
        )
        await self.pg_session.flush()

    async def _apply_savings_transfer(self, transfer: Transfer) -> None:
        """Entry point kept for the legacy job runner."""
        await self.execute_transfer_run(transfer)

    # --- notifications ---

    async def _receiver_ids(self, transfer: Transfer) -> list[UUID]:
        if transfer.to_scope == "PERSONAL":
            return [transfer.to_user_id] if transfer.to_user_id else []
        ids = await self._family_member_ids(transfer.to_family_id)
        return [i for i in ids if i != transfer.created_by]

    async def _notify(self, transfer: Transfer, user_ids: list[UUID], *, type_: str, title: str, body: str, actions=None) -> None:
        family_id = transfer.to_family_id if transfer.to_scope == "FAMILY" else None
        for uid in user_ids:
            self.pg_session.add(
                Notification(
                    user_id=uid,
                    family_id=family_id,
                    type=type_,
                    title=title,
                    body=body,
                    related_entity_type="TRANSFER",
                    related_entity_id=transfer.id,
                    allowed_actions={"actions": actions or ["DISMISS"]},
                    status=NOTIF_STATUS_UNREAD,
                )
            )

    async def _notify_offer(self, transfer: Transfer) -> None:
        labels = await self.labels([transfer])
        sender = self.endpoint_label(labels, transfer.from_scope, transfer.family_id, transfer.from_user_id)
        await self._notify(
            transfer,
            await self._receiver_ids(transfer),
            type_="TRANSFER_OFFER",
            title=f"{sender} wants to send you {transfer.amount}",
            body=(transfer.note or "Open Transfers to accept or decline."),
            actions=["ACCEPT", "DECLINE"],
        )

    async def notify_failed(self, transfer: Transfer, reason: str) -> None:
        await self._notify(
            transfer,
            [transfer.created_by],
            type_="TRANSFER_FAILED",
            title=f"Scheduled transfer of {transfer.amount} failed",
            body=reason,
        )

    # --- recurring ---

    async def is_direct_now(self, parent: Transfer) -> bool:
        return await self._is_direct(
            actor_id=parent.from_user_id or parent.created_by,
            from_scope=parent.from_scope,
            family_id=parent.family_id,
            to_scope=parent.to_scope,
            to_family_id=parent.to_family_id,
            to_user_id=parent.to_user_id,
        )

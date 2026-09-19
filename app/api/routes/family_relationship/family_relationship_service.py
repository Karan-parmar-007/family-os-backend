from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.family.model import Family, FamilyRelationship
from app.api.routes.family_relationship.family_relationship_schemas import (
    FamilyRelationshipCreateRequest,
)
from app.api.routes.family_relationship.family_relationship_schemas import (
    FamilyConnectByCodeRequest,
)
from app.api.routes.user.model import UserBase, UserFamilyLink

RELATIONSHIP_PENDING = "PENDING"
RELATIONSHIP_ACTIVE = "ACTIVE"
RELATIONSHIP_REJECTED = "REJECTED"
RELATIONSHIP_REMOVED = "REMOVED"


class FamilyRelationshipService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def list_relationships(self, family_id: UUID) -> list[FamilyRelationship]:
        stmt = (
            select(FamilyRelationship)
            .where(
                or_(
                    FamilyRelationship.family_a_id == family_id,
                    FamilyRelationship.family_b_id == family_id,
                )
            )
            .order_by(FamilyRelationship.created_at.desc())
        )
        return list((await self.pg_session.execute(stmt)).scalars().all())

    async def create_relationship_request(
        self,
        family_id: UUID,
        user_id: UUID,
        request: FamilyRelationshipCreateRequest,
    ) -> FamilyRelationship:
        target_family_id = await self._resolve_target_family_by_manager_email(
            source_family_id=family_id,
            email=request.target_member_email,
        )
        await self._assert_no_active_or_pending_pair(family_id, target_family_id)

        relationship = FamilyRelationship(
            family_a_id=family_id,
            family_b_id=target_family_id,
            relationship_type=request.relationship_type,
            label=request.label,
            status=RELATIONSHIP_PENDING,
            initiated_by_family_id=family_id,
            initiated_by_user_id=user_id,
        )
        self.pg_session.add(relationship)
        await self.pg_session.commit()
        await self.pg_session.refresh(relationship)
        return relationship

    async def get_relationship(self, relationship_id: UUID) -> FamilyRelationship | None:
        return await self.pg_session.get(FamilyRelationship, relationship_id)

    async def accept_relationship(
        self,
        family_id: UUID,
        user_id: UUID,
        relationship: FamilyRelationship,
    ) -> FamilyRelationship:
        if relationship.status != RELATIONSHIP_PENDING:
            raise ValueError("Only pending relationships can be accepted")
        if family_id not in {relationship.family_a_id, relationship.family_b_id}:
            raise PermissionError("Relationship does not belong to this family")
        if relationship.initiated_by_family_id == family_id:
            raise PermissionError("Initiating family cannot accept its own request")

        relationship.status = RELATIONSHIP_ACTIVE
        relationship.responded_by_user_id = user_id
        await self.pg_session.commit()
        await self.pg_session.refresh(relationship)
        return relationship

    async def reject_relationship(
        self,
        family_id: UUID,
        user_id: UUID,
        relationship: FamilyRelationship,
    ) -> FamilyRelationship:
        if relationship.status != RELATIONSHIP_PENDING:
            raise ValueError("Only pending relationships can be rejected")
        if family_id not in {relationship.family_a_id, relationship.family_b_id}:
            raise PermissionError("Relationship does not belong to this family")
        if relationship.initiated_by_family_id == family_id:
            raise PermissionError("Initiating family cannot reject its own request")

        relationship.status = RELATIONSHIP_REJECTED
        relationship.responded_by_user_id = user_id
        await self.pg_session.commit()
        await self.pg_session.refresh(relationship)
        return relationship

    async def remove_relationship(
        self,
        family_id: UUID,
        user_id: UUID,
        relationship: FamilyRelationship,
    ) -> FamilyRelationship:
        if relationship.status != RELATIONSHIP_ACTIVE:
            raise ValueError("Only active relationships can be removed")
        if family_id not in {relationship.family_a_id, relationship.family_b_id}:
            raise PermissionError("Relationship does not belong to this family")

        relationship.status = RELATIONSHIP_REMOVED
        relationship.responded_by_user_id = user_id
        await self.pg_session.commit()
        await self.pg_session.refresh(relationship)
        return relationship

    async def require_active_relationship(self, family_a_id: UUID, family_b_id: UUID) -> None:
        stmt = select(FamilyRelationship.id).where(
            FamilyRelationship.status == RELATIONSHIP_ACTIVE,
            or_(
                and_(
                    FamilyRelationship.family_a_id == family_a_id,
                    FamilyRelationship.family_b_id == family_b_id,
                ),
                and_(
                    FamilyRelationship.family_a_id == family_b_id,
                    FamilyRelationship.family_b_id == family_a_id,
                ),
            ),
        )
        row = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ValueError("No active relationship exists between these families")

    async def get_join_code(self, family_id: UUID) -> str:
        family = await self.pg_session.get(Family, family_id)
        if family is None:
            raise ValueError("Family not found")
        code = family.link_code or family.join_code
        if not code:
            raise ValueError("Family has no link code")
        return code

    async def connect_by_join_code(
        self,
        family_id: UUID,
        user_id: UUID,
        request: FamilyConnectByCodeRequest,
    ) -> FamilyRelationship:
        raw = request.join_code.strip()
        if not (raw.isdigit() and len(raw) == 8):
            raise ValueError("Invalid join code format")

        stmt = select(Family.id).where(or_(Family.link_code == raw, Family.join_code == raw))
        target_family_id = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        if target_family_id is None:
            raise ValueError("No family found for this join code")
        if target_family_id == family_id:
            raise ValueError("Cannot connect a family to itself")

        await self._assert_no_active_or_pending_pair(family_id, target_family_id)

        relationship = FamilyRelationship(
            family_a_id=family_id,
            family_b_id=target_family_id,
            relationship_type=None,
            label=request.label,
            status=RELATIONSHIP_ACTIVE,
            initiated_by_family_id=family_id,
            initiated_by_user_id=user_id,
            responded_by_user_id=user_id,
        )
        self.pg_session.add(relationship)
        await self.pg_session.commit()
        await self.pg_session.refresh(relationship)
        return relationship

    async def _resolve_target_family_by_manager_email(
        self, source_family_id: UUID, email: str
    ) -> UUID:
        stmt = (
            select(UserFamilyLink.family_id)
            .join(UserBase, UserBase.id == UserFamilyLink.user_id)
            .where(
                UserBase.email == email,
                UserFamilyLink.is_family_manager.is_(True),
                UserFamilyLink.family_id != source_family_id,
            )
        )
        families = list((await self.pg_session.execute(stmt)).scalars().all())
        unique_families = list(set(families))
        if not unique_families:
            raise ValueError("No managed family found for target email")
        if len(unique_families) > 1:
            raise ValueError("Target email manages multiple families; cannot infer target")
        return unique_families[0]

    async def _assert_no_active_or_pending_pair(self, family_a_id: UUID, family_b_id: UUID) -> None:
        stmt = select(FamilyRelationship.id).where(
            FamilyRelationship.status.in_([RELATIONSHIP_PENDING, RELATIONSHIP_ACTIVE]),
            or_(
                and_(
                    FamilyRelationship.family_a_id == family_a_id,
                    FamilyRelationship.family_b_id == family_b_id,
                ),
                and_(
                    FamilyRelationship.family_a_id == family_b_id,
                    FamilyRelationship.family_b_id == family_a_id,
                ),
            ),
        )
        existing = (await self.pg_session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            raise ValueError("An active or pending relationship already exists")

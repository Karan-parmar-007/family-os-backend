from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.assets.assets_schemas import AssetCreateRequest, AssetUpdateRequest
from app.api.routes.assets.model import FamilyAssets, PersonalAsset
from app.api.routes.category.category_service import CategoryService
from app.api.schemas.pagination import PaginationParams
from app.core.scope import ScopeContext

UNCATEGORIZED = "Uncategorized"


class AssetsService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    def _visible_family(self, family_id: UUID, user_id: UUID):
        return and_(
            FamilyAssets.family_id == family_id,
            or_(
                FamilyAssets.access_level == "FAMILY",
                FamilyAssets.in_someone_name == user_id,
                FamilyAssets.created_by == user_id,
            ),
        )

    def _visible_personal(self, family_id: UUID, user_id: UUID):
        return and_(
            PersonalAsset.family_id == family_id,
            or_(PersonalAsset.user_id == user_id, PersonalAsset.access_level == "FAMILY"),
        )

    async def _load_page(
        self, ids: list[tuple[UUID, bool]]
    ) -> list[tuple[FamilyAssets | PersonalAsset, bool]]:
        fam_ids = [i for i, p in ids if not p]
        per_ids = [i for i, p in ids if p]
        found: dict[UUID, FamilyAssets | PersonalAsset] = {}
        if fam_ids:
            for row in (await self.pg_session.execute(select(FamilyAssets).where(FamilyAssets.id.in_(fam_ids)))).scalars():
                found[row.id] = row
        if per_ids:
            for row in (await self.pg_session.execute(select(PersonalAsset).where(PersonalAsset.id.in_(per_ids)))).scalars():
                found[row.id] = row
        return [(found[i], p) for i, p in ids if i in found]

    async def list_assets(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext,
        category_id: UUID | None = None,
    ) -> tuple[list[tuple[FamilyAssets | PersonalAsset, bool]], int, Decimal]:
        fam_where = [self._visible_family(family_id, scope_ctx.user_id)]
        per_where = [self._visible_personal(family_id, scope_ctx.user_id)]
        if category_id:
            fam_where.append(FamilyAssets.category_id == category_id)
            per_where.append(PersonalAsset.category_id == category_id)
        combined = union_all(
            select(
                FamilyAssets.id.label("id"),
                literal(False).label("is_personal"),
                FamilyAssets.created_at.label("created_at"),
                FamilyAssets.value.label("value"),
            ).where(*fam_where),
            select(
                PersonalAsset.id.label("id"),
                literal(True).label("is_personal"),
                PersonalAsset.created_at.label("created_at"),
                PersonalAsset.value.label("value"),
            ).where(*per_where),
        ).subquery()

        total, total_value = (
            await self.pg_session.execute(
                select(func.count(), func.coalesce(func.sum(combined.c.value), 0))
            )
        ).one()
        page = (
            await self.pg_session.execute(
                select(combined.c.id, combined.c.is_personal)
                .order_by(combined.c.created_at.desc(), combined.c.id.desc())
                .offset(pagination.offset)
                .limit(pagination.page_size)
            )
        ).all()
        rows = await self._load_page([(r.id, r.is_personal) for r in page])
        return rows, int(total), Decimal(str(total_value))

    async def list_personal_assets(
        self,
        user_id: UUID,
        pagination: PaginationParams,
        *,
        category_id: UUID | None = None,
    ) -> tuple[list[PersonalAsset], int, Decimal]:
        where = [PersonalAsset.user_id == user_id]
        if category_id:
            where.append(PersonalAsset.category_id == category_id)
        total, total_value = (
            await self.pg_session.execute(
                select(func.count(), func.coalesce(func.sum(PersonalAsset.value), 0)).where(*where)
            )
        ).one()
        rows = (
            await self.pg_session.execute(
                select(PersonalAsset)
                .where(*where)
                .order_by(PersonalAsset.created_at.desc(), PersonalAsset.id.desc())
                .offset(pagination.offset)
                .limit(pagination.page_size)
            )
        ).scalars().all()
        return list(rows), int(total), Decimal(str(total_value))

    async def _category_name(
        self, category_id: UUID | None, *, user_id: UUID, is_personal: bool, family_id: UUID
    ) -> str:
        cat = await CategoryService(self.pg_session).require_usable(
            category_id,
            user_id=user_id,
            scope="PERSONAL" if is_personal else "FAMILY",
            family_id=None if is_personal else family_id,
            category_type="ASSET",
        )
        return cat.name if cat else UNCATEGORIZED

    async def create_asset(
        self, family_id: UUID, user_id: UUID, request: AssetCreateRequest
    ) -> tuple[FamilyAssets | PersonalAsset, bool]:
        is_personal = request.is_personal
        type_name = await self._category_name(
            request.category_id, user_id=user_id, is_personal=is_personal, family_id=family_id
        )
        common = dict(
            family_id=family_id,
            asset_name=request.asset_name.strip(),
            type=type_name,
            category_id=request.category_id,
            value=request.value,
            quantity=request.quantity or Decimal("1"),
            quantity_label=request.quantity_label,
            acquired_on=request.acquired_on,
            notes=request.notes,
            document_id=request.document_id,
        )
        if is_personal:
            asset: FamilyAssets | PersonalAsset = PersonalAsset(
                user_id=user_id,
                scope_type="PERSONAL",
                access_level=request.access_level if request.access_level in {"PRIVATE", "FAMILY"} else "PRIVATE",
                **common,
            )
        else:
            asset = FamilyAssets(
                scope_type="FAMILY",
                in_someone_name=request.in_someone_name,
                access_level=request.access_level or "FAMILY",
                created_by=user_id,
                let_everyone_edit=request.let_everyone_edit,
                **common,
            )
        self.pg_session.add(asset)
        await self.pg_session.commit()
        await self.pg_session.refresh(asset)
        return asset, is_personal

    async def create_personal_asset(
        self, user_id: UUID, family_id: UUID, request: AssetCreateRequest
    ) -> PersonalAsset:
        asset, _ = await self.create_asset(
            family_id, user_id, request.model_copy(update={"is_personal": True})
        )
        return asset  # type: ignore[return-value]

    async def get_asset(
        self, asset_id: UUID, family_id: UUID
    ) -> tuple[FamilyAssets | PersonalAsset, bool] | None:
        for model, is_personal in ((FamilyAssets, False), (PersonalAsset, True)):
            row = (
                await self.pg_session.execute(
                    select(model).where(model.id == asset_id, model.family_id == family_id)
                )
            ).scalar_one_or_none()
            if row:
                return row, is_personal
        return None

    async def get_personal_asset(self, asset_id: UUID, user_id: UUID) -> PersonalAsset | None:
        return (
            await self.pg_session.execute(
                select(PersonalAsset).where(
                    PersonalAsset.id == asset_id, PersonalAsset.user_id == user_id
                )
            )
        ).scalar_one_or_none()

    async def update_asset(
        self,
        asset: FamilyAssets | PersonalAsset,
        request: AssetUpdateRequest,
        *,
        actor_id: UUID,
        is_head: bool = False,
    ) -> FamilyAssets | PersonalAsset:
        is_personal = isinstance(asset, PersonalAsset)
        data = request.model_dump(exclude_unset=True)
        if "category_id" in data:
            asset.type = await self._category_name(
                data["category_id"], user_id=actor_id, is_personal=is_personal, family_id=asset.family_id
            )
            asset.category_id = data.pop("category_id")
        data.pop("type", None)
        if "let_everyone_edit" in data:
            flag = bool(data.pop("let_everyone_edit"))
            if not is_personal and flag != asset.let_everyone_edit:
                if actor_id != asset.created_by and not is_head:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Only the creator or a family head can change who may edit",
                    )
                asset.let_everyone_edit = flag
        if is_personal and data.get("access_level") not in (None, "PRIVATE", "FAMILY"):
            data["access_level"] = "PRIVATE"
        for field, value in data.items():
            if value is None and field in {"asset_name", "value", "access_level"}:
                continue
            setattr(asset, field, value)
        await self.pg_session.commit()
        await self.pg_session.refresh(asset)
        return asset

    async def delete_asset(self, asset: FamilyAssets | PersonalAsset) -> None:
        await self.pg_session.delete(asset)
        await self.pg_session.commit()

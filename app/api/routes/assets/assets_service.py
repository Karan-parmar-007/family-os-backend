from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.assets.assets_schemas import AssetCreateRequest, AssetUpdateRequest
from app.api.routes.assets.model import FamilyAssets, PersonalAsset
from app.api.schemas.pagination import PaginationParams
from app.core.scope import ScopeContext, filter_entity_rows


class AssetsService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def list_assets(
        self,
        family_id: UUID,
        pagination: PaginationParams,
        *,
        scope_ctx: ScopeContext | None = None,
    ) -> tuple[list[tuple[object, bool]], int, Decimal]:
        family_rows = list(
            (await self.pg_session.execute(
                select(FamilyAssets).where(FamilyAssets.family_id == family_id)
            )).scalars().all()
        )
        personal_rows = list(
            (await self.pg_session.execute(
                select(PersonalAsset).where(PersonalAsset.family_id == family_id)
            )).scalars().all()
        )
        combined = [(a, False) for a in family_rows] + [(a, True) for a in personal_rows]
        combined = filter_entity_rows(scope_ctx, combined)
        combined.sort(key=lambda x: x[0].created_at, reverse=True)
        total_value = sum((a.value for a, _ in combined), Decimal("0"))
        total = len(combined)
        page = combined[pagination.offset : pagination.offset + pagination.page_size]
        return page, total, total_value

    async def list_personal_assets(
        self,
        user_id: UUID,
        pagination: PaginationParams,
    ) -> tuple[list[PersonalAsset], int, Decimal]:
        rows = list(
            (
                await self.pg_session.execute(
                    select(PersonalAsset).where(PersonalAsset.user_id == user_id)
                )
            ).scalars().all()
        )
        rows.sort(key=lambda a: a.created_at, reverse=True)
        total_value = sum((a.value for a in rows), Decimal("0"))
        total = len(rows)
        return rows[pagination.offset : pagination.offset + pagination.page_size], total, total_value

    async def create_asset(
        self, family_id: UUID, user_id: UUID, request: AssetCreateRequest
    ) -> tuple[FamilyAssets | PersonalAsset, bool]:
        if request.is_personal:
            asset = PersonalAsset(
                family_id=family_id,
                user_id=user_id,
                scope_type=request.scope_type or "PERSONAL",
                asset_name=request.asset_name,
                type=request.type,
                value=request.value,
                quantity=request.quantity or Decimal("1"),
                quantity_label=request.quantity_label,
                acquired_on=request.acquired_on,
                notes=request.notes,
                document_id=request.document_id,
                access_level=request.access_level or "PRIVATE",
            )
            self.pg_session.add(asset)
            await self.pg_session.commit()
            await self.pg_session.refresh(asset)
            return asset, True
        asset = FamilyAssets(
            family_id=family_id,
            scope_type=request.scope_type,
            asset_name=request.asset_name,
            type=request.type,
            value=request.value,
            quantity=request.quantity or Decimal("1"),
            quantity_label=request.quantity_label,
            acquired_on=request.acquired_on,
            notes=request.notes,
            document_id=request.document_id,
            in_someone_name=request.in_someone_name,
            access_level=request.access_level or "FAMILY",
        )
        self.pg_session.add(asset)
        await self.pg_session.commit()
        await self.pg_session.refresh(asset)
        return asset, False

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
        self, asset: FamilyAssets | PersonalAsset, request: AssetUpdateRequest
    ) -> FamilyAssets | PersonalAsset:
        for field, value in request.model_dump(exclude_none=True).items():
            setattr(asset, field, value)
        await self.pg_session.commit()
        await self.pg_session.refresh(asset)
        return asset

    async def delete_asset(self, asset: FamilyAssets | PersonalAsset) -> None:
        await self.pg_session.delete(asset)
        await self.pg_session.commit()

"""User-created categories.

FAMILY scope: one list per family, shared by all its members (any member may
add; creator or a head may rename/delete). A member's other families never see
it. PERSONAL scope: private to its owner across all families.
"""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.category.category_model import FosCategory
from app.api.routes.category.category_schemas import (
    CATEGORY_TYPES,
    CategoryCreateRequest,
    CategoryUpdateRequest,
)
from app.api.routes.user.model import UserFamilyLink
from app.api.schemas.pagination import PaginationParams
from app.core.scope import can_edit_shared


def _invalid(errors: dict[str, str]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": "Validation failed", "errors": errors},
    )


def _norm_type(raw: str | None) -> str:
    cat_type = (raw or "").upper().strip()
    if cat_type not in CATEGORY_TYPES:
        raise _invalid({"categoryType": f"Allowed: {', '.join(CATEGORY_TYPES)}"})
    return cat_type


def _norm_scope(raw: str | None) -> str:
    scope = (raw or "FAMILY").upper().strip()
    if scope not in {"FAMILY", "PERSONAL"}:
        raise _invalid({"scope": "Scope must be FAMILY or PERSONAL"})
    return scope


class CategoryService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def _membership(self, user_id: UUID, family_id: UUID) -> UserFamilyLink | None:
        stmt = select(UserFamilyLink).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id == family_id,
        )
        return (await self.pg_session.execute(stmt)).scalars().first()

    async def _require_member(self, user_id: UUID, family_id: UUID | None) -> UserFamilyLink:
        if family_id is None:
            raise _invalid({"familyId": "family_id is required for FAMILY scope"})
        link = await self._membership(user_id, family_id)
        if link is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this family")
        return link

    async def can_edit(self, user_id: UUID, cat: FosCategory) -> bool:
        if cat.scope == "PERSONAL":
            return cat.owner_user_id == user_id
        link = await self._membership(user_id, cat.family_id) if cat.family_id else None
        if link is None:
            return False
        return can_edit_shared(
            actor_id=user_id,
            creator_id=cat.owner_user_id,
            is_head=link.is_family_manager,
            let_everyone_edit=False,
        )

    def _list_filter(self, scope: str, cat_type: str, *, user_id: UUID, family_id: UUID | None):
        if scope == "FAMILY":
            return [
                FosCategory.scope == "FAMILY",
                FosCategory.family_id == family_id,
                FosCategory.category_type == cat_type,
            ]
        return [
            FosCategory.scope == "PERSONAL",
            FosCategory.owner_user_id == user_id,
            FosCategory.category_type == cat_type,
        ]

    async def list_categories(
        self,
        user_id: UUID,
        scope: str,
        category_type: str,
        family_id: Optional[UUID] = None,
        *,
        pagination: PaginationParams,
        q: str | None = None,
    ) -> tuple[list[FosCategory], int, bool]:
        """Returns (rows, total, is_head)."""
        scope = _norm_scope(scope)
        cat_type = _norm_type(category_type)
        is_head = False
        if scope == "FAMILY":
            is_head = (await self._require_member(user_id, family_id)).is_family_manager

        filters = self._list_filter(scope, cat_type, user_id=user_id, family_id=family_id)
        if q and q.strip():
            filters.append(func.lower(FosCategory.name).contains(q.strip().lower(), autoescape=True))

        total = (
            await self.pg_session.execute(select(func.count()).select_from(FosCategory).where(*filters))
        ).scalar_one()
        rows = (
            await self.pg_session.execute(
                select(FosCategory)
                .where(*filters)
                .order_by(func.lower(FosCategory.name), FosCategory.id)
                .offset(pagination.offset)
                .limit(pagination.page_size)
            )
        ).scalars().all()
        return list(rows), total, is_head

    async def create_category(self, user_id: UUID, req: CategoryCreateRequest) -> FosCategory:
        name = (req.name or "").strip()
        if not name:
            raise _invalid({"name": "Category name is required"})
        scope = _norm_scope(req.scope)
        cat_type = _norm_type(req.category_type)
        family_id = req.family_id if scope == "FAMILY" else None
        if scope == "FAMILY":
            await self._require_member(user_id, family_id)

        filters = self._list_filter(scope, cat_type, user_id=user_id, family_id=family_id)
        existing = (
            await self.pg_session.execute(
                select(FosCategory).where(*filters, func.lower(FosCategory.name) == name.lower())
            )
        ).scalars().first()
        if existing:
            return existing

        cat = FosCategory(
            scope=scope,
            family_id=family_id,
            owner_user_id=user_id,
            category_type=cat_type,
            name=name,
            color=req.color,
            icon=req.icon,
        )
        self.pg_session.add(cat)
        try:
            await self.pg_session.commit()
        except IntegrityError:
            await self.pg_session.rollback()
            # Lost a race with an identical create; return the winner.
            return (
                await self.pg_session.execute(
                    select(FosCategory).where(*filters, func.lower(FosCategory.name) == name.lower())
                )
            ).scalars().one()
        await self.pg_session.refresh(cat)
        return cat

    async def _get_editable(self, user_id: UUID, category_id: UUID) -> FosCategory:
        cat = await self.pg_session.get(FosCategory, category_id)
        if cat is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
        if cat.scope == "FAMILY":
            await self._require_member(user_id, cat.family_id)
        if not await self.can_edit(user_id, cat):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the person who created this category or a family head can change it",
            )
        return cat

    async def update_category(
        self, user_id: UUID, category_id: UUID, req: CategoryUpdateRequest
    ) -> FosCategory:
        cat = await self._get_editable(user_id, category_id)
        if req.name is not None:
            name = req.name.strip()
            if not name:
                raise _invalid({"name": "Category name is required"})
            cat.name = name
        if req.color is not None:
            cat.color = req.color or None
        if req.icon is not None:
            cat.icon = req.icon or None
        await self._sync_name_snapshots(cat)
        try:
            await self.pg_session.commit()
        except IntegrityError:
            await self.pg_session.rollback()
            raise _invalid({"name": "A category with this name already exists"})
        await self.pg_session.refresh(cat)
        return cat

    async def _sync_name_snapshots(self, cat: FosCategory) -> None:
        """Assets, insurance and vault keep a readable name next to category_id."""
        from app.api.routes.assets.model import FamilyAssets, PersonalAsset
        from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
        from app.api.routes.vault.model import FosVaultItem

        for model, col in (
            (FamilyAssets, "type"),
            (PersonalAsset, "type"),
            (FamilyInsurance, "type"),
            (PersonalInsurance, "type"),
            (FosVaultItem, "category"),
        ):
            await self.pg_session.execute(
                update(model).where(model.category_id == cat.id).values({col: cat.name})
            )

    async def delete_category(self, user_id: UUID, category_id: UUID) -> None:
        """Items keep their name snapshot; their category_id is cleared by the FK."""
        cat = await self._get_editable(user_id, category_id)
        await self.pg_session.delete(cat)
        await self.pg_session.commit()

    async def require_usable(
        self,
        category_id: UUID | None,
        *,
        user_id: UUID,
        scope: str,
        family_id: UUID | None,
        category_type: str | tuple[str, ...],
    ) -> FosCategory | None:
        """Validate that a submitted category belongs to the list the item lives in."""
        if category_id is None:
            return None
        cat = await self.pg_session.get(FosCategory, category_id)
        types = (category_type,) if isinstance(category_type, str) else category_type
        ok = cat is not None and cat.category_type in types and cat.scope == scope
        if ok and scope == "FAMILY":
            ok = cat.family_id == family_id
        elif ok:
            ok = cat.owner_user_id == user_id
        if not ok:
            raise _invalid({"categoryId": "Pick a category from this list"})
        return cat

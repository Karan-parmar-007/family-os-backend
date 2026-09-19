from typing import List, Optional, Tuple
from uuid import UUID
import uuid6
from fastapi import HTTPException, status
from sqlalchemy import select, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.category.category_model import FosCategory
from app.api.routes.category.category_schemas import CategoryCreateRequest
from app.api.routes.user.model import UserFamilyLink

DEFAULT_CATEGORIES = {
    "INCOME": [
        "Salary",
        "Freelance / Consulting",
        "Investments & Dividends",
        "Rental Income",
        "Business",
        "Gifts & Grants",
        "Other Income",
    ],
    "EXPENSE": [
        "Housing & Rent",
        "Groceries & Food",
        "Utilities & Bills",
        "Transportation & Fuel",
        "Healthcare & Medical",
        "Entertainment & Leisure",
        "Shopping",
        "Education",
        "Insurance",
        "Subscriptions",
        "Other Expense",
    ],
    "DEBT": [
        "Home Mortgage",
        "Auto / Vehicle Loan",
        "Credit Card",
        "Student Loan",
        "Personal Loan",
        "Family Loan",
        "Other Debt",
    ],
    "ASSET": [
        "Real Estate & Land",
        "Vehicles & Transport",
        "Gold & Precious Metals",
        "Jewelry & Valuables",
        "Electronics & Tech",
        "Furniture & Appliances",
        "Collectibles & Art",
        "Other Asset",
    ],
    "VAULT_PASSWORD": [
        "Banking & Finance",
        "Email & Primary Accounts",
        "Work & Services",
        "Social Media",
        "Shopping & Utilities",
        "Streaming & Entertainment",
        "Other Password",
    ],
    "VAULT_DOCUMENT": [
        "Identity & Passports",
        "Tax & Financial Statements",
        "Property Deeds & Titles",
        "Medical & Health",
        "Legal Contracts & Agreements",
        "Receipts & Warranties",
        "Other Document",
    ],
}

VALID_TYPES = {"INCOME", "EXPENSE", "DEBT", "ASSET", "VAULT_PASSWORD", "VAULT_DOCUMENT"}


class CategoryService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def _check_family_membership(self, user_id: UUID, family_id: UUID) -> bool:
        stmt = select(UserFamilyLink).where(
            UserFamilyLink.user_id == user_id,
            UserFamilyLink.family_id == family_id,
        )
        res = (await self.pg_session.execute(stmt)).scalars().first()
        return res is not None

    async def seed_defaults_if_empty(
        self, scope: str, category_type: str, family_id: Optional[UUID] = None, user_id: Optional[UUID] = None
    ) -> None:
        cat_type = category_type.upper()
        defaults = DEFAULT_CATEGORIES.get(cat_type, ["General", "Other"])

        stmt = select(func.count(FosCategory.id)).where(
            FosCategory.category_type == cat_type,
            FosCategory.scope == scope,
        )
        if scope == "FAMILY" and family_id:
            stmt = stmt.where(FosCategory.family_id == family_id)
        elif scope == "PERSONAL" and user_id:
            stmt = stmt.where(FosCategory.owner_user_id == user_id)

        count = (await self.pg_session.execute(stmt)).scalar() or 0
        if count == 0:
            for name in defaults:
                cat = FosCategory(
                    scope=scope,
                    family_id=family_id if scope == "FAMILY" else None,
                    owner_user_id=user_id if scope == "PERSONAL" else None,
                    category_type=cat_type,
                    name=name,
                    color=None,
                    icon=None,
                    is_default=True,
                )
                self.pg_session.add(cat)
            await self.pg_session.commit()

    async def list_categories(
        self,
        user_id: UUID,
        scope: str,
        category_type: str,
        family_id: Optional[UUID] = None,
    ) -> List[FosCategory]:
        cat_type = category_type.upper()
        if scope == "FAMILY":
            if not family_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"message": "Validation failed", "errors": {"familyId": "family_id is required for FAMILY scope"}},
                )
            is_member = await self._check_family_membership(user_id, family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            await self.seed_defaults_if_empty("FAMILY", cat_type, family_id=family_id)
            stmt = select(FosCategory).where(
                FosCategory.scope == "FAMILY",
                FosCategory.family_id == family_id,
                FosCategory.category_type == cat_type,
            ).order_by(FosCategory.is_default.desc(), FosCategory.name.asc())
        else:
            await self.seed_defaults_if_empty("PERSONAL", cat_type, user_id=user_id)
            stmt = select(FosCategory).where(
                FosCategory.scope == "PERSONAL",
                FosCategory.owner_user_id == user_id,
                FosCategory.category_type == cat_type,
            ).order_by(FosCategory.is_default.desc(), FosCategory.name.asc())

        items = (await self.pg_session.execute(stmt)).scalars().all()
        return list(items)

    async def create_category(self, user_id: UUID, req: CategoryCreateRequest) -> FosCategory:
        errors = {}
        name_clean = (req.name or "").strip()
        if not name_clean:
            errors["name"] = "Category name is required and cannot be empty"
        elif len(name_clean) > 64:
            errors["name"] = "Category name cannot exceed 64 characters"

        cat_type = (req.category_type or "").upper().strip()
        if not cat_type:
            errors["categoryType"] = "Category type is required"
        elif cat_type not in VALID_TYPES:
            errors["categoryType"] = f"Invalid category type. Allowed: {', '.join(sorted(VALID_TYPES))}"

        scope_clean = (req.scope or "FAMILY").upper().strip()
        if scope_clean not in {"FAMILY", "PERSONAL"}:
            errors["scope"] = "Scope must be either 'FAMILY' or 'PERSONAL'"
        elif scope_clean == "FAMILY" and not req.family_id:
            errors["familyId"] = "family_id is required for FAMILY scope"

        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "Validation failed", "errors": errors},
            )

        if scope_clean == "FAMILY":
            assert req.family_id is not None
            is_member = await self._check_family_membership(user_id, req.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

            # Check duplicate
            dup_stmt = select(FosCategory).where(
                FosCategory.scope == "FAMILY",
                FosCategory.family_id == req.family_id,
                FosCategory.category_type == cat_type,
                func.lower(FosCategory.name) == name_clean.lower(),
            )
            existing = (await self.pg_session.execute(dup_stmt)).scalars().first()
            if existing:
                return existing

            cat = FosCategory(
                scope="FAMILY",
                family_id=req.family_id,
                owner_user_id=user_id,
                category_type=cat_type,
                name=name_clean,
                color=req.color,
                icon=req.icon,
                is_default=False,
            )
        else:
            dup_stmt = select(FosCategory).where(
                FosCategory.scope == "PERSONAL",
                FosCategory.owner_user_id == user_id,
                FosCategory.category_type == cat_type,
                func.lower(FosCategory.name) == name_clean.lower(),
            )
            existing = (await self.pg_session.execute(dup_stmt)).scalars().first()
            if existing:
                return existing

            cat = FosCategory(
                scope="PERSONAL",
                family_id=None,
                owner_user_id=user_id,
                category_type=cat_type,
                name=name_clean,
                color=req.color,
                icon=req.icon,
                is_default=False,
            )

        self.pg_session.add(cat)
        await self.pg_session.commit()
        await self.pg_session.refresh(cat)
        return cat

    async def delete_category(self, user_id: UUID, category_id: UUID) -> None:
        cat = (await self.pg_session.execute(select(FosCategory).where(FosCategory.id == category_id))).scalars().first()
        if not cat:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

        if cat.is_default:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete default system categories")

        if cat.scope == "FAMILY":
            is_member = await self._check_family_membership(user_id, cat.family_id)
            if not is_member:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        else:
            if cat.owner_user_id != user_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        await self.pg_session.delete(cat)
        await self.pg_session.commit()

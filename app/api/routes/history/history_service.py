"""Aggregate completion history across entity types (Plan 11)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.debt.model import Debt, DebtScopeView
from app.api.routes.goals.model import FamilyGoal, PersonalGoal
from app.api.routes.insurance.model import FamilyInsurance, PersonalInsurance
from app.api.routes.investments.model import FamilyInvestment, PersonalInvestment
from app.api.routes.savings_plans.model import FamilySavingsPlan, PersonalSavingsPlan
from app.api.routes.history.history_schemas import HistoryItem
from app.core.scope import ScopeContext, can_view_scoped_entity, load_scope_context


def _fmt(amount: Decimal | float | str) -> str:
    return f"{Decimal(str(amount)):,.2f}"


class HistoryService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

    async def list_family_history(
        self,
        family_id: UUID,
        user_id: UUID,
        *,
        entity_type: str | None = None,
        limit: int = 50,
    ) -> list[HistoryItem]:
        ctx = await load_scope_context(self.pg_session, user_id, family_id)
        items: list[HistoryItem] = []

        if entity_type in (None, "ALL", "DEBT"):
            items.extend(await self._family_debts(family_id, ctx))
        if entity_type in (None, "ALL", "INVESTMENT"):
            items.extend(await self._family_investments(family_id, ctx))
        if entity_type in (None, "ALL", "PLAN"):
            items.extend(await self._family_plans(family_id, ctx))
        if entity_type in (None, "ALL", "GOAL"):
            items.extend(await self._family_goals(family_id, ctx))
        if entity_type in (None, "ALL", "INSURANCE"):
            items.extend(await self._family_insurance(family_id, ctx))

        items.sort(key=lambda i: i.completed_at, reverse=True)
        return items[:limit]

    async def list_personal_history(
        self,
        user_id: UUID,
        *,
        entity_type: str | None = None,
        limit: int = 50,
    ) -> list[HistoryItem]:
        items: list[HistoryItem] = []
        if entity_type in (None, "ALL", "DEBT"):
            items.extend(await self._personal_debts(user_id))
        if entity_type in (None, "ALL", "INVESTMENT"):
            items.extend(await self._personal_investments(user_id))
        if entity_type in (None, "ALL", "PLAN"):
            items.extend(await self._personal_plans(user_id))
        if entity_type in (None, "ALL", "GOAL"):
            items.extend(await self._personal_goals(user_id))
        if entity_type in (None, "ALL", "INSURANCE"):
            items.extend(await self._personal_insurance(user_id))
        items.sort(key=lambda i: i.completed_at, reverse=True)
        return items[:limit]

    async def _family_debts(self, family_id: UUID, ctx: ScopeContext) -> list[HistoryItem]:
        raw_rows = list(
            (
                await self.pg_session.execute(
                    select(Debt, DebtScopeView)
                    .join(DebtScopeView, DebtScopeView.debt_id == Debt.id)
                    .where(
                        DebtScopeView.scope_kind == "FAMILY",
                        DebtScopeView.family_id == family_id,
                        or_(
                            DebtScopeView.user_id.is_(None),
                            DebtScopeView.user_id == ctx.user_id,
                        ),
                        Debt.status == "PAID",
                        Debt.completed_at.is_not(None),
                    )
                )
            ).all()
        )
        rows: dict[UUID, tuple[Debt, DebtScopeView]] = {}
        for debt, view in raw_rows:
            current = rows.get(debt.id)
            if current is None or view.user_id == ctx.user_id:
                rows[debt.id] = (debt, view)
        out: list[HistoryItem] = []
        for d, view in rows.values():
            if view.excluded:
                continue
            has_viewer_override = view.user_id == ctx.user_id
            if not can_view_scoped_entity(
                ctx,
                scope_type="FAMILY",
                owner_user_id=d.owner_user_id,
                access_level="FAMILY" if has_viewer_override else view.access_level,
                entity_id=d.id,
            ):
                continue
            out.append(
                HistoryItem(
                    entity_type="DEBT",
                    id=d.id,
                    name=d.debt_name,
                    headline=f"Paid ₹{_fmt(d.total_amount or d.remaining_amount or 0)}",
                    completed_at=d.completed_at,  # type: ignore[arg-type]
                    terminal_status=d.status,
                )
            )
        return out

    async def _personal_debts(self, user_id: UUID) -> list[HistoryItem]:
        rows = list(
            (
                await self.pg_session.execute(
                    select(Debt)
                    .join(DebtScopeView, DebtScopeView.debt_id == Debt.id)
                    .where(
                        DebtScopeView.scope_kind == "PERSONAL",
                        DebtScopeView.user_id == user_id,
                        DebtScopeView.excluded.is_(False),
                        Debt.status == "PAID",
                        Debt.completed_at.is_not(None),
                    )
                )
            ).scalars().all()
        )
        return [
            HistoryItem(
                entity_type="DEBT",
                id=d.id,
                name=d.debt_name,
                headline=f"Paid ₹{_fmt(d.total_amount or d.remaining_amount or 0)}",
                completed_at=d.completed_at,  # type: ignore[arg-type]
                terminal_status=d.status,
            )
            for d in rows
        ]

    async def _family_investments(self, family_id: UUID, ctx: ScopeContext) -> list[HistoryItem]:
        rows = list(
            (
                await self.pg_session.execute(
                    select(FamilyInvestment).where(
                        FamilyInvestment.family_id == family_id,
                        FamilyInvestment.status.in_(("MATURED", "CLOSED")),
                        FamilyInvestment.completed_at.is_not(None),
                    )
                )
            ).scalars().all()
        )
        out: list[HistoryItem] = []
        for inv in rows:
            if not can_view_scoped_entity(
                ctx,
                scope_type=getattr(inv, "scope_type", "FAMILY"),
                owner_user_id=getattr(inv, "in_someone_name", None),
                access_level=getattr(inv, "access_level", "FAMILY"),
            ):
                continue
            val = inv.maturity_amount or inv.current_value or Decimal("0")
            out.append(
                HistoryItem(
                    entity_type="INVESTMENT",
                    id=inv.id,
                    name=inv.investment_name,
                    headline=f"Matured at ₹{_fmt(val)}",
                    completed_at=inv.completed_at,  # type: ignore[arg-type]
                    terminal_status=inv.status,
                )
            )
        return out

    async def _personal_investments(self, user_id: UUID) -> list[HistoryItem]:
        rows = list(
            (
                await self.pg_session.execute(
                    select(PersonalInvestment).where(
                        PersonalInvestment.user_id == user_id,
                        PersonalInvestment.status.in_(("MATURED", "CLOSED")),
                        PersonalInvestment.completed_at.is_not(None),
                    )
                )
            ).scalars().all()
        )
        return [
            HistoryItem(
                entity_type="INVESTMENT",
                id=inv.id,
                name=inv.investment_name,
                headline=f"Matured at ₹{_fmt(inv.maturity_amount or inv.current_value or 0)}",
                completed_at=inv.completed_at,  # type: ignore[arg-type]
                terminal_status=inv.status,
            )
            for inv in rows
        ]

    async def _family_plans(self, family_id: UUID, ctx: ScopeContext) -> list[HistoryItem]:
        rows = list(
            (
                await self.pg_session.execute(
                    select(FamilySavingsPlan).where(
                        FamilySavingsPlan.family_id == family_id,
                        FamilySavingsPlan.status == "COMPLETED",
                        FamilySavingsPlan.completed_at.is_not(None),
                    )
                )
            ).scalars().all()
        )
        out: list[HistoryItem] = []
        for p in rows:
            if not can_view_scoped_entity(
                ctx,
                scope_type=getattr(p, "scope_type", "FAMILY"),
                owner_user_id=getattr(p, "in_someone_name", None),
                access_level=getattr(p, "access_level", "FAMILY"),
            ):
                continue
            out.append(
                HistoryItem(
                    entity_type="PLAN",
                    id=p.id,
                    name=p.plan_name,
                    headline=f"Reached target ₹{_fmt(p.target_amount)}",
                    completed_at=p.completed_at,  # type: ignore[arg-type]
                    terminal_status=p.status,
                )
            )
        return out

    async def _personal_plans(self, user_id: UUID) -> list[HistoryItem]:
        rows = list(
            (
                await self.pg_session.execute(
                    select(PersonalSavingsPlan).where(
                        PersonalSavingsPlan.user_id == user_id,
                        PersonalSavingsPlan.status == "COMPLETED",
                        PersonalSavingsPlan.completed_at.is_not(None),
                    )
                )
            ).scalars().all()
        )
        return [
            HistoryItem(
                entity_type="PLAN",
                id=p.id,
                name=p.plan_name,
                headline=f"Reached target ₹{_fmt(p.target_amount)}",
                completed_at=p.completed_at,  # type: ignore[arg-type]
                terminal_status=p.status,
            )
            for p in rows
        ]

    async def _family_goals(self, family_id: UUID, ctx: ScopeContext) -> list[HistoryItem]:
        rows = list(
            (
                await self.pg_session.execute(
                    select(FamilyGoal).where(
                        FamilyGoal.family_id == family_id,
                        FamilyGoal.status == "ACHIEVED",
                        FamilyGoal.completed_at.is_not(None),
                    )
                )
            ).scalars().all()
        )
        out: list[HistoryItem] = []
        for g in rows:
            if not can_view_scoped_entity(
                ctx,
                scope_type=getattr(g, "scope_type", "FAMILY"),
                owner_user_id=getattr(g, "in_someone_name", None),
                access_level=getattr(g, "access_level", "FAMILY"),
            ):
                continue
            out.append(
                HistoryItem(
                    entity_type="GOAL",
                    id=g.id,
                    name=g.goal_name,
                    headline=f"Achieved ₹{_fmt(g.target_amount)}",
                    completed_at=g.completed_at,  # type: ignore[arg-type]
                    terminal_status=g.status,
                )
            )
        return out

    async def _personal_goals(self, user_id: UUID) -> list[HistoryItem]:
        rows = list(
            (
                await self.pg_session.execute(
                    select(PersonalGoal).where(
                        PersonalGoal.user_id == user_id,
                        PersonalGoal.status == "ACHIEVED",
                        PersonalGoal.completed_at.is_not(None),
                    )
                )
            ).scalars().all()
        )
        return [
            HistoryItem(
                entity_type="GOAL",
                id=g.id,
                name=g.goal_name,
                headline=f"Achieved ₹{_fmt(g.target_amount)}",
                completed_at=g.completed_at,  # type: ignore[arg-type]
                terminal_status=g.status,
            )
            for g in rows
        ]

    async def _family_insurance(self, family_id: UUID, ctx: ScopeContext) -> list[HistoryItem]:
        rows = list(
            (
                await self.pg_session.execute(
                    select(FamilyInsurance).where(
                        FamilyInsurance.family_id == family_id,
                        FamilyInsurance.status.in_(("MATURED", "LAPSED")),
                        FamilyInsurance.completed_at.is_not(None),
                    )
                )
            ).scalars().all()
        )
        out: list[HistoryItem] = []
        for ins in rows:
            if not can_view_scoped_entity(
                ctx,
                scope_type=getattr(ins, "scope_type", "FAMILY"),
                owner_user_id=getattr(ins, "insured_member", None),
                access_level=getattr(ins, "access_level", "FAMILY"),
            ):
                continue
            out.append(
                HistoryItem(
                    entity_type="INSURANCE",
                    id=ins.id,
                    name=ins.insurance_name,
                    headline=f"{ins.status.title()} — ₹{_fmt(ins.coverage_amount or 0)}",
                    completed_at=ins.completed_at,  # type: ignore[arg-type]
                    terminal_status=ins.status,
                )
            )
        return out

    async def _personal_insurance(self, user_id: UUID) -> list[HistoryItem]:
        rows = list(
            (
                await self.pg_session.execute(
                    select(PersonalInsurance).where(
                        PersonalInsurance.user_id == user_id,
                        PersonalInsurance.status.in_(("MATURED", "LAPSED")),
                        PersonalInsurance.completed_at.is_not(None),
                    )
                )
            ).scalars().all()
        )
        return [
            HistoryItem(
                entity_type="INSURANCE",
                id=ins.id,
                name=ins.insurance_name,
                headline=f"{ins.status.title()} — ₹{_fmt(ins.coverage_amount or 0)}",
                completed_at=ins.completed_at,  # type: ignore[arg-type]
                terminal_status=ins.status,
            )
            for ins in rows
        ]

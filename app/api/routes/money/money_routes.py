import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUserDep, PGSessionDep
from app.api.routes.money.money_schemas import (
    MoneyRuleCreateRequest,
    MoneyRuleUpdateRequest,
    MoneyRuleResponse,
    MoneyRuleListResponse,
    MoneyEventCreateRequest,
    MoneyEventResponse,
    MoneyEventListResponse,
    PartyResponse,
)
from app.api.routes.money.money_service import MoneyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/money", tags=["money"])


def get_money_service(session: PGSessionDep) -> MoneyService:
    return MoneyService(session)


def _format_rule(r) -> MoneyRuleResponse:
    return MoneyRuleResponse(
        id=r.id,
        scope=r.scope,
        family_id=r.family_id,
        owner_user_id=r.owner_user_id,
        kind=r.kind,
        name=r.name,
        amount=float(r.amount),
        category_id=r.category_id,
        frequency=r.frequency,
        next_run_at=r.next_run_at,
        document_id=r.document_id,
        let_everyone_edit=r.let_everyone_edit,
        created_by=r.created_by,
        insurance_id=r.insurance_id,
        debt_id=r.debt_id,
        status=r.status,
        parties=[PartyResponse(id=p.id, party_type=p.party_type, user_id=p.user_id) for p in (r.parties or [])],
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _format_event(e) -> MoneyEventResponse:
    return MoneyEventResponse(
        id=e.id,
        rule_id=e.rule_id,
        scope=e.scope,
        family_id=e.family_id,
        owner_user_id=e.owner_user_id,
        kind=e.kind,
        name=e.name,
        amount=float(e.amount),
        category_id=e.category_id,
        document_id=e.document_id,
        let_everyone_edit=e.let_everyone_edit,
        occurred_at=e.occurred_at,
        created_by=e.created_by,
        parties=[PartyResponse(id=p.id, party_type=p.party_type, user_id=p.user_id) for p in (e.parties or [])],
        created_at=e.created_at,
    )


# --- Rules (Recurring) ---

@router.post("/rules", response_model=MoneyRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_money_rule(
    request: MoneyRuleCreateRequest,
    current_user: CurrentUserDep,
    service: MoneyService = Depends(get_money_service),
) -> MoneyRuleResponse:
    rule = await service.create_rule(current_user.id, request)
    return _format_rule(rule)


@router.get("/rules", response_model=MoneyRuleListResponse)
async def list_money_rules(
    current_user: CurrentUserDep,
    scope: str = Query(default="FAMILY"),
    family_id: Optional[UUID] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    service: MoneyService = Depends(get_money_service),
) -> MoneyRuleListResponse:
    rules = await service.list_rules(current_user.id, scope=scope, family_id=family_id, kind=kind)
    return MoneyRuleListResponse(items=[_format_rule(r) for r in rules])


@router.patch("/rules/{rule_id}", response_model=MoneyRuleResponse)
async def update_money_rule(
    rule_id: UUID,
    request: MoneyRuleUpdateRequest,
    current_user: CurrentUserDep,
    service: MoneyService = Depends(get_money_service),
) -> MoneyRuleResponse:
    rule = await service.update_rule(current_user.id, rule_id, request)
    return _format_rule(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_money_rule(
    rule_id: UUID,
    current_user: CurrentUserDep,
    service: MoneyService = Depends(get_money_service),
):
    await service.delete_rule(current_user.id, rule_id)


# --- Events (One-Time Hits) ---

@router.post("/events", response_model=MoneyEventResponse, status_code=status.HTTP_201_CREATED)
async def create_money_event(
    request: MoneyEventCreateRequest,
    current_user: CurrentUserDep,
    service: MoneyService = Depends(get_money_service),
) -> MoneyEventResponse:
    event = await service.create_event(current_user.id, request)
    return _format_event(event)


@router.get("/events", response_model=MoneyEventListResponse)
async def list_money_events(
    current_user: CurrentUserDep,
    scope: str = Query(default="FAMILY"),
    family_id: Optional[UUID] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    source: Optional[str] = Query(
        default=None,
        description="ONE_TIME | RECURRING — filter by manual vs cron-materialized events",
    ),
    category_id: Optional[UUID] = Query(default=None),
    from_date: Optional[str] = Query(default=None, description="ISO datetime lower bound"),
    to_date: Optional[str] = Query(default=None, description="ISO datetime upper bound"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: MoneyService = Depends(get_money_service),
) -> MoneyEventListResponse:
    from datetime import datetime

    def _parse_dt(raw: Optional[str]):
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    events, total = await service.list_events(
        current_user.id,
        scope=scope,
        family_id=family_id,
        kind=kind,
        source=source,
        category_id=category_id,
        from_date=_parse_dt(from_date),
        to_date=_parse_dt(to_date),
        limit=limit,
        offset=offset,
    )
    return MoneyEventListResponse(items=[_format_event(e) for e in events], total=total)

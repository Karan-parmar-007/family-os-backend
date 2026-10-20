import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import CurrentUserDep, PGSessionDep
from app.api.routes.money.model import FosMoneyEvent, FosMoneyRule
from app.api.routes.money.money_schemas import (
    MoneyEventCreateRequest,
    MoneyEventListResponse,
    MoneyEventResponse,
    MoneyEventUpdateRequest,
    MoneyRuleCreateRequest,
    MoneyRuleListResponse,
    MoneyRuleResponse,
    MoneyRuleUpdateRequest,
    PartyResponse,
)
from app.api.routes.money.money_service import MoneyService
from app.api.schemas.pagination import PaginationDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/money", tags=["money"])


def get_money_service(session: PGSessionDep) -> MoneyService:
    return MoneyService(session)


def _parties(rows) -> list[PartyResponse]:
    return [PartyResponse(id=p.id, party_type=p.party_type, user_id=p.user_id) for p in (rows or [])]


def _format_rule(r: FosMoneyRule, can_edit: bool) -> MoneyRuleResponse:
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
        every_n=r.every_n or 1,
        next_run_at=r.next_run_at,
        last_run_at=r.last_run_at,
        run_count=r.run_count or 0,
        end_at=r.end_at,
        max_runs=r.max_runs,
        document_id=r.document_id,
        let_everyone_edit=r.let_everyone_edit,
        can_edit=can_edit,
        created_by=r.created_by,
        insurance_id=r.insurance_id,
        debt_id=r.debt_id,
        status=r.status,
        parties=_parties(r.parties),
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _format_event(e: FosMoneyEvent, can_edit: bool = False) -> MoneyEventResponse:
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
        is_overdrawn=e.is_overdrawn,
        can_edit=can_edit,
        occurred_at=e.occurred_at,
        created_by=e.created_by,
        parties=_parties(e.parties),
        created_at=e.created_at,
    )


def _parse_dt(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


# --- Rules (recurring) ---

@router.post("/rules", response_model=MoneyRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_money_rule(
    request: MoneyRuleCreateRequest,
    current_user: CurrentUserDep,
    service: MoneyService = Depends(get_money_service),
) -> MoneyRuleResponse:
    rule = await service.create_rule(current_user.id, request)
    return _format_rule(rule, True)


@router.get("/rules", response_model=MoneyRuleListResponse)
async def list_money_rules(
    current_user: CurrentUserDep,
    pagination: PaginationDep,
    scope: str = Query(default="FAMILY"),
    family_id: Optional[UUID] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=100),
    service: MoneyService = Depends(get_money_service),
) -> MoneyRuleListResponse:
    rules, total = await service.list_rules(
        current_user.id, scope=scope, family_id=family_id, kind=kind, pagination=pagination, q=q
    )
    items = [_format_rule(r, await service.can_edit_rule(current_user.id, r)) for r in rules]
    return MoneyRuleListResponse.from_page(items, total=total, pagination=pagination)


@router.patch("/rules/{rule_id}", response_model=MoneyRuleResponse)
async def update_money_rule(
    rule_id: UUID,
    request: MoneyRuleUpdateRequest,
    current_user: CurrentUserDep,
    service: MoneyService = Depends(get_money_service),
) -> MoneyRuleResponse:
    rule = await service.update_rule(current_user.id, rule_id, request)
    return _format_rule(rule, True)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_money_rule(
    rule_id: UUID,
    current_user: CurrentUserDep,
    service: MoneyService = Depends(get_money_service),
):
    await service.delete_rule(current_user.id, rule_id)


# --- Events (one-time entries and recurring runs) ---

@router.post("/events", response_model=MoneyEventResponse, status_code=status.HTTP_201_CREATED)
async def create_money_event(
    request: MoneyEventCreateRequest,
    current_user: CurrentUserDep,
    service: MoneyService = Depends(get_money_service),
) -> MoneyEventResponse:
    event = await service.create_event(current_user.id, request)
    return _format_event(event, True)


@router.get("/events", response_model=MoneyEventListResponse)
async def list_money_events(
    current_user: CurrentUserDep,
    pagination: PaginationDep,
    scope: str = Query(default="FAMILY"),
    family_id: Optional[UUID] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    source: Optional[str] = Query(
        default=None,
        description="ONE_TIME | RECURRING — manual entries vs scheduled runs",
    ),
    category_id: Optional[UUID] = Query(default=None),
    rule_id: Optional[UUID] = Query(default=None),
    from_date: Optional[str] = Query(default=None, description="ISO datetime lower bound"),
    to_date: Optional[str] = Query(default=None, description="ISO datetime upper bound"),
    q: Optional[str] = Query(default=None, max_length=100),
    service: MoneyService = Depends(get_money_service),
) -> MoneyEventListResponse:
    events, total = await service.list_events(
        current_user.id,
        scope=scope,
        family_id=family_id,
        kind=kind,
        source=source,
        category_id=category_id,
        rule_id=rule_id,
        from_date=_parse_dt(from_date),
        to_date=_parse_dt(to_date),
        q=q,
        pagination=pagination,
    )
    return MoneyEventListResponse.from_page(
        [_format_event(e, await service.can_edit_event(current_user.id, e)) for e in events],
        total=total,
        pagination=pagination,
    )


@router.patch("/events/{event_id}", response_model=MoneyEventResponse)
async def update_money_event(
    event_id: UUID,
    request: MoneyEventUpdateRequest,
    current_user: CurrentUserDep,
    service: MoneyService = Depends(get_money_service),
) -> MoneyEventResponse:
    event = await service.update_event(current_user.id, event_id, request)
    return _format_event(event, True)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_money_event(
    event_id: UUID,
    current_user: CurrentUserDep,
    service: MoneyService = Depends(get_money_service),
):
    await service.delete_event(current_user.id, event_id)

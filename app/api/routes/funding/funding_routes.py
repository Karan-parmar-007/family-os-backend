"""Funding split plan and breakdown API routes (Plan 01)."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import select

from app.api.all_dependencies.login_required import LoggedInUserDep
from app.api.all_dependencies.part_of_the_family import LoggedInFamilyMemberDep
from app.api.db_dependencies import PGSessionDep
from app.core.funding_service import FundingBreakdownEntry, FundingService, PaymentSplitLine, PaymentSplitPlan

router = APIRouter(prefix="/funding", tags=["funding"])
family_router = APIRouter(prefix="/families/{family_id}/funding-breakdown", tags=["funding"])


class SplitLineIn(BaseModel):
    pool_type: str
    family_id: UUID | None = None
    user_id: UUID | None = None
    amount: str
    expected_total: str | None = None
    obligation_remaining: str | None = None

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SaveSplitPlanRequest(BaseModel):
    entity_type: str
    entity_id: UUID
    lines: list[SplitLineIn]

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SplitPlanResponse(BaseModel):
    lines: list[SplitLineIn]

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class BreakdownEntryResponse(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    job_id: UUID | None = None
    pool_type: str
    family_id: UUID | None = None
    user_id: UUID | None = None
    amount: str
    direction: str
    created_at: str

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class BreakdownListResponse(BaseModel):
    entries: list[BreakdownEntryResponse]

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


def _line_resp(line: PaymentSplitLine) -> SplitLineIn:
    return SplitLineIn(
        pool_type=line.pool_type,
        family_id=line.family_id,
        user_id=line.user_id,
        amount=str(line.amount),
        expected_total=(
            str(line.expected_total) if line.expected_total is not None else None
        ),
        obligation_remaining=(
            str(line.obligation_remaining)
            if line.obligation_remaining is not None
            else None
        ),
    )


def _entry_resp(entry: FundingBreakdownEntry) -> BreakdownEntryResponse:
    return BreakdownEntryResponse(
        id=entry.id,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        job_id=entry.job_id,
        pool_type=entry.pool_type,
        family_id=entry.family_id,
        user_id=entry.user_id,
        amount=str(entry.amount),
        direction=entry.direction,
        created_at=entry.created_at.isoformat(),
    )


@router.post("/split-plan", status_code=status.HTTP_200_OK)
async def save_split_plan(
    user: LoggedInUserDep,
    session: PGSessionDep,
    request: SaveSplitPlanRequest,
) -> dict[str, str]:
    fs = FundingService(session)
    await fs.save_split_plan(
        request.entity_type,
        request.entity_id,
        [
            {
                "pool_type": ln.pool_type,
                "family_id": ln.family_id,
                "user_id": ln.user_id,
                "amount": ln.amount,
                "expected_total": ln.expected_total,
                "obligation_remaining": ln.obligation_remaining,
            }
            for ln in request.lines
        ],
    )
    await session.commit()
    return {"message": "ok"}


@router.get("/split-plan/{entity_type}/{entity_id}", response_model=SplitPlanResponse)
async def get_split_plan(
    user: LoggedInUserDep,
    session: PGSessionDep,
    entity_type: str,
    entity_id: UUID,
) -> SplitPlanResponse:
    fs = FundingService(session)
    lines = await fs.load_split_plan(entity_type, entity_id)
    if not lines:
        return SplitPlanResponse(lines=[])
    return SplitPlanResponse(lines=[_line_resp(ln) for ln in lines])


@router.get("/breakdown/{job_id}", response_model=BreakdownListResponse)
async def get_breakdown_by_job(
    user: LoggedInUserDep,
    session: PGSessionDep,
    job_id: UUID,
) -> BreakdownListResponse:
    rows = list(
        (
            await session.execute(
                select(FundingBreakdownEntry)
                .where(FundingBreakdownEntry.job_id == job_id)
                .order_by(FundingBreakdownEntry.created_at.asc())
            )
        ).scalars().all()
    )
    return BreakdownListResponse(entries=[_entry_resp(e) for e in rows])


@family_router.get("", response_model=BreakdownListResponse)
async def get_breakdown_by_entity(
    family_member: LoggedInFamilyMemberDep,
    session: PGSessionDep,
    family_id: UUID,
    entity_type: str = Query(...),
    entity_id: UUID = Query(...),
) -> BreakdownListResponse:
    rows = list(
        (
            await session.execute(
                select(FundingBreakdownEntry)
                .where(
                    FundingBreakdownEntry.entity_type == entity_type,
                    FundingBreakdownEntry.entity_id == entity_id,
                )
                .order_by(FundingBreakdownEntry.created_at.desc())
            )
        ).scalars().all()
    )
    return BreakdownListResponse(entries=[_entry_resp(e) for e in rows])

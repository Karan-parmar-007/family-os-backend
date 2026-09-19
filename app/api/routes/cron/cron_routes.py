from fastapi import APIRouter, Query

from app.api.db_dependencies import PGSessionDep
from app.api.dependencies import CurrentUserDep
from app.scheduler.fos_tick import run_fos_tick

router = APIRouter(prefix="/cron", tags=["cron"])


@router.post("/run")
async def run_cron_now(
    _user: CurrentUserDep,
    session: PGSessionDep,
    force: bool = Query(
        False,
        description="Apply every ACTIVE money rule / recurring transfer even if next_run is in the future.",
    ),
) -> dict:
    """Manually fire the same tick the interval scheduler uses (for local testing)."""
    stats = await run_fos_tick(session, force=force)
    return {
        "moneyRulesApplied": stats["money_rules_applied"],
        "transferOffers": stats["transfer_offers"],
        "forced": force,
    }

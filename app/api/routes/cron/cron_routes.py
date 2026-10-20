from fastapi import APIRouter, HTTPException, Query, status

from app.api.db_dependencies import PGSessionDep
from app.api.dependencies import CurrentUserDep
from app.auth.dependencies import IdentityDep, is_app_admin
from app.scheduler.fos_tick import run_fos_tick

router = APIRouter(prefix="/cron", tags=["cron"])


@router.post("/run")
async def run_cron_now(
    _user: CurrentUserDep,
    identity: IdentityDep,
    session: PGSessionDep,
    force: bool = Query(
        False,
        description="Admins only: apply every ACTIVE rule / recurring transfer even if not yet due.",
    ),
) -> dict:
    """Run the same tick the interval scheduler uses; only due items are posted."""
    if force and not is_app_admin(identity):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can force a run")
    stats = await run_fos_tick(session, force=force)
    return {
        "moneyRulesApplied": stats.get("money_rules_applied", 0),
        "insuranceInstallmentsPaid": stats.get("insurance_installments_paid", 0),
        "transferRuns": stats.get("transfer_runs", 0),
        "skipped": bool(stats.get("skipped")),
        "forced": force,
    }

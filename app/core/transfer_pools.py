"""Map transfer scope strings to savings pool references."""

from uuid import UUID

from app.core.constants import (
    POOL_FAMILY,
    POOL_PERSONAL,
    SCOPE_FAMILY,
)
from app.core.savings_ledger_service import SavingsPoolRef


def scope_to_pool(
    scope: str,
    *,
    family_id: UUID | None = None,
    user_id: UUID | None = None,
) -> SavingsPoolRef:
    if scope == SCOPE_FAMILY:
        if family_id is None:
            raise ValueError("family_id required for FAMILY scope")
        return SavingsPoolRef(pool_type=POOL_FAMILY, family_id=family_id)
    if scope == "PERSONAL":
        if not user_id:
            raise ValueError("user_id required for PERSONAL scope")
        return SavingsPoolRef(pool_type=POOL_PERSONAL, user_id=user_id)
    raise ValueError(f"Unknown scope: {scope}")

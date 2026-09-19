from fastapi import APIRouter

router = APIRouter(prefix="/families/{family_id}/savings", tags=["savings"])

from fastapi import APIRouter
from app.api.routes.health import health_routes

main_router = APIRouter()
main_router.include_router(health_routes.router)
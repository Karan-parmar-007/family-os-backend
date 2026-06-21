from fastapi import APIRouter

from app.api.routes.auth import auth_routes
from app.api.routes.family import family_routes
from app.api.routes.health import health_routes
from app.api.routes.user import user_routes

main_router = APIRouter(prefix="/api")
main_router.include_router(health_routes.router)
main_router.include_router(auth_routes.router)
main_router.include_router(user_routes.router)
main_router.include_router(family_routes.router)

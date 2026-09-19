from fastapi import APIRouter

from app.api.routes.assets import assets_routes, personal_assets_routes
from app.api.routes.auth import auth_routes
from app.api.routes.profile import profile_routes
from app.api.routes.admin import admin_routes
from app.api.routes.currency import public_routes as currency_public_routes
from app.api.routes.currency import currency_routes
from app.api.routes.debt import simple_debt_routes
from app.api.routes.document import document_routes, user_document_routes
from app.api.routes.family import family_routes
from app.api.routes.family_relationship import family_relationship_routes
from app.api.routes.health import health_routes
from app.api.routes.insurance import insurance_routes, personal_insurance_routes
from app.api.routes.money import money_routes
from app.api.routes.category import category_routes
from app.api.routes.vault import vault_routes
from app.api.routes.savings import savings_routes
from app.api.routes.notification import notification_routes
from app.api.routes.transfer import transfer_routes, personal_transfer_routes
from app.api.routes.friend import friend_routes
from app.api.routes.upcoming import upcoming_routes
from app.api.routes.user import user_routes
from app.api.routes.cron import cron_routes

main_router = APIRouter(prefix="/api/familyos")

main_router.include_router(health_routes.router)
main_router.include_router(auth_routes.router)
main_router.include_router(profile_routes.router)
main_router.include_router(admin_routes.router)
main_router.include_router(currency_public_routes.router)
main_router.include_router(currency_routes.router)
main_router.include_router(user_routes.router)
main_router.include_router(friend_routes.router)
main_router.include_router(family_routes.router)
main_router.include_router(family_relationship_routes.router)
main_router.include_router(transfer_routes.router)
main_router.include_router(personal_transfer_routes.router)
main_router.include_router(notification_routes.router)

# Money rules & events (Income / Expense rewrite)
main_router.include_router(money_routes.router)
main_router.include_router(simple_debt_routes.router)
main_router.include_router(category_routes.router)
main_router.include_router(vault_routes.router)

# Document & Storage
main_router.include_router(document_routes.router)
main_router.include_router(user_document_routes.router)

# Savings & Assets
main_router.include_router(savings_routes.router)
main_router.include_router(assets_routes.router)
main_router.include_router(personal_assets_routes.router)
main_router.include_router(insurance_routes.router)
main_router.include_router(personal_insurance_routes.router)
main_router.include_router(upcoming_routes.router)
main_router.include_router(upcoming_routes.personal_router)
main_router.include_router(cron_routes.router)

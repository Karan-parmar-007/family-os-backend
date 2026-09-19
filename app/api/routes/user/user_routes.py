# app/api/routes/user/user_routes.py
# Old /users/me (local users table) migrated to /me routes in profile_routes.py.
# Global savings will be re-implemented in Phase 7 (Income and Expense).
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/users', tags=['users'])

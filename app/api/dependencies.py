# app/api/dependencies.py

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select

from app.api.auth_cookies import ACCESS_TOKEN_COOKIE
from app.api.db_dependencies import GarageClientDep, MongoDBDep, PGSessionDep
from app.api.routes.auth.auth_service import AuthService
from app.api.routes.health.health_service import HealthService
from app.api.routes.user.model import UserBase
from app.api.routes.user.user_service import UserService
from app.utils.security_and_auth import ACCESS_AUDIENCE, decode_token
from app.api.routes.family.family_service import FamilyService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_health_service(
    session: PGSessionDep,
    mongo: MongoDBDep,
    garage_client: GarageClientDep,
) -> HealthService:
    return HealthService(
        pg_session=session,
        mongo_db=mongo,
        garage_client=garage_client,
    )


async def get_auth_service(
    session: PGSessionDep,
    mongo: MongoDBDep,
) -> AuthService:
    return AuthService(pg_session=session, mongo_db=mongo)


async def get_user_service(
    session: PGSessionDep,
) -> UserService:
    return UserService(pg_session=session)


async def get_family_service(
    session: PGSessionDep,
    mongo: MongoDBDep,
    garage_client: GarageClientDep,
) -> FamilyService:
    return FamilyService(
        pg_session=session,
        mongo_db=mongo,
        garage_client=garage_client,
    )


async def get_current_user(
    request: Request,
    session: PGSessionDep,
    bearer_token: Annotated[str | None, Depends(oauth2_scheme)] = None,
) -> UserBase:
    """Validate access token from HttpOnly cookie or Authorization header."""
    raw_token = request.cookies.get(ACCESS_TOKEN_COOKIE) or bearer_token
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_token(raw_token, audience=ACCESS_AUDIENCE)
        user_id_str = payload.get("sub")
        if not isinstance(user_id_str, str):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    stmt = select(UserBase).where(UserBase.id == UUID(user_id_str))
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


type HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
type AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
type UserServiceDep = Annotated[UserService, Depends(get_user_service)]
type CurrentUserDep = Annotated[UserBase, Depends(get_current_user)]
type FamilyServiceDep = Annotated[FamilyService, Depends(get_family_service)]

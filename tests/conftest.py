import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import db_settings


@pytest.fixture(scope="session", autouse=True)
def _register_sqlmodel_tables():
    """Ensure all SQLModel tables are registered before ORM queries in tests."""
    from app.api.main_router import main_router  # noqa: F401


@pytest.fixture(autouse=True)
def _mock_sso_me(monkeypatch):
    """Avoid 5s HTTP connect timeouts to external localhost:8000 during test execution."""
    from app.auth import dependencies, sso_client

    async def _mock_fetch(*args, **kwargs):
        return {"role_name": "member", "name": "Test User"}

    monkeypatch.setattr(sso_client, "fetch_sso_me", _mock_fetch)
    monkeypatch.setattr(dependencies, "fetch_sso_me", _mock_fetch)


@pytest.fixture
async def db_session() -> AsyncSession:
    """Yield a rolled-back session against the configured database."""
    engine = create_async_engine(db_settings.POSTGRES_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
            await session.rollback()
    except (OSError, ConnectionRefusedError):
        pytest.skip("Database not available")
    finally:
        await engine.dispose()


@pytest.fixture
async def any_family_id(db_session: AsyncSession):
    try:
        row = (await db_session.execute(text("SELECT id FROM families LIMIT 1"))).scalar_one_or_none()
    except (OSError, ConnectionRefusedError):
        pytest.skip("Database not available")
    if row is None:
        pytest.skip("No families in database")
    return row

# main.py
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from karan_sso.fastapi import CSRFMiddleware

from app.api.main_router import main_router
from app.auth.sso import configure_sso, sso_settings
from app.core.errors import register_exception_handlers
from app.config import auth_settings, cors_settings, scheduler_settings
from app.db.garage_session import GarageSession
from app.db.mongo_session import MongoSession
from app.db.postgress_session import PostgresSession
from app.scheduler.fos_tick import run_fos_tick

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _scheduler_tick() -> None:
    pg = PostgresSession()
    async with pg._sessionmaker() as session:
        try:
            stats = await run_fos_tick(session)
            if stats:
                logger.info("Scheduler tick: %s", stats)
        except Exception:
            logger.exception("Scheduler tick failed")
        finally:
            await pg.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_session = MongoSession()
    postgres_session = PostgresSession()
    garage_session = GarageSession()

    app.state.mongo_session = mongo_session
    app.state.postgres_session = postgres_session
    app.state.garage_session = garage_session

    try:
        await mongo_session.connect()
        await postgres_session.verify_connection()
        logger.info("PostgreSQL connected successfully")
        await _scheduler_tick()
    except Exception as exc:
        logger.exception("Startup verify or scheduler failed: %s", exc)

    scheduler: AsyncIOScheduler | None = None
    if scheduler_settings.SCHEDULER_ENABLED:
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            _scheduler_tick,
            "interval",
            minutes=scheduler_settings.SCHEDULER_TICK_MINUTES,
            coalesce=True,
            misfire_grace_time=3600,
            id="family_os_tick",
        )
        scheduler.start()
        app.state.scheduler = scheduler
        logger.info(
            "Scheduler enabled: tick every %s minute(s)",
            scheduler_settings.SCHEDULER_TICK_MINUTES,
        )
    else:
        logger.warning("Interval scheduler disabled; due jobs only run on startup or POST /api/familyos/cron/run")

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)
    await mongo_session.close()
    await postgres_session.dispose()


configure_sso()

_docs_enabled = not auth_settings.is_production
app = FastAPI(
    title="Family OS",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)
register_exception_handlers(app)
# Sign-in / refresh / logout live in SSO (/api/auth/*, routed by Caddy / the Vite proxy).
app.add_middleware(
    CSRFMiddleware,
    exempt_prefixes=("/health", "/api/familyos/health"),
    settings=sso_settings,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", sso_settings.CSRF_HEADER_NAME],
)
app.include_router(main_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

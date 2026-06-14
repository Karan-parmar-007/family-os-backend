# main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.main_router import main_router
from app.api.middlewares.csrf import CSRFMiddleware
from app.db.garage_session import GarageSession
from app.db.mongo_session import MongoSession
from app.db.postgress_session import PostgresSession


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_session = MongoSession()
    postgres_session = PostgresSession()
    garage_session = GarageSession()

    await mongo_session.connect()
    await postgres_session.verify_connection()

    app.state.mongo_session = mongo_session
    app.state.postgres_session = postgres_session
    app.state.garage_session = garage_session

    yield

    await mongo_session.close()
    await postgres_session.dispose()


app = FastAPI(title="Family OS", lifespan=lifespan)
app.add_middleware(CSRFMiddleware)
app.include_router(main_router)

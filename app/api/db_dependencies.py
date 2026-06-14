# app/api/db_dependencies.py

from typing import Annotated, AsyncGenerator

from botocore.client import BaseClient
from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase
from sqlalchemy.ext.asyncio import AsyncSession


async def _get_pg_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    postgres_manager = request.app.state.postgres_session
    async for session in postgres_manager.get_session():
        yield session


async def _get_mongo_db(request: Request) -> AsyncGenerator[AsyncDatabase, None]:
    mongo_manager = request.app.state.mongo_session
    async for db in mongo_manager.get_db():
        yield db


async def _get_garage_client(request: Request) -> AsyncGenerator[BaseClient, None]:
    garage_manager = request.app.state.garage_session
    async for client in garage_manager.get_client():
        yield client


PGSessionDep = Annotated[AsyncSession, Depends(_get_pg_session)]
MongoDBDep = Annotated[AsyncDatabase, Depends(_get_mongo_db)]
GarageClientDep = Annotated[BaseClient, Depends(_get_garage_client)]

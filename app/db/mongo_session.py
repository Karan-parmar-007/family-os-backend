# app/db/mongo_session.py

from pymongo import AsyncMongoClient
from app.config import db_settings
from pymongo.asynchronous.database import AsyncDatabase
from typing import AsyncGenerator, Optional

class MongoSession:
    """
    Manages the MongoDB database connection and sessions.
    """
    
    def __init__(self):
        self._client: Optional[AsyncMongoClient] = None
        self._db: Optional[AsyncDatabase] = None

    async def connect(self):
        """
        Establishes a connection to the MongoDB database.
        """
        self._client = AsyncMongoClient(db_settings.MONGO_URI)
        self._db = self._client[db_settings.MONGO_DB_NAME]

    async def get_db(self) -> AsyncGenerator[AsyncDatabase, None]:
        """
        Provides an asynchronous generator for the MongoDB database instance.
        """
        if self._db is None:
            await self.connect()
        yield self._db

    async def close(self):
        """
        Closes the MongoDB client connection.
        """
        if self._client:
            await self._client.close()
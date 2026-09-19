from sqlalchemy.ext.asyncio import AsyncSession


class SavingsService:
    def __init__(self, pg_session: AsyncSession):
        self.pg_session = pg_session

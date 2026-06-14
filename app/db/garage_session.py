# app/db/garage_session.py

from typing import AsyncGenerator

import aioboto3
from botocore.client import BaseClient, Config

from app.config import db_settings

# aioboto3 uses the S3 API wire protocol — required for Garage, not AWS-specific naming in our code.
_GARAGE_SERVICE = "s3"


class GarageSession:
    """Manages async Garage object-storage connections (path-style, SigV4)."""

    def __init__(self) -> None:
        self._session = aioboto3.Session()

    async def get_client(self) -> AsyncGenerator[BaseClient, None]:
        """
        Yields a request-scoped Garage client.
        Injected via FastAPI Depends() — see app/api/db_dependencies.py.
        """
        garage_config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        )

        async with self._session.client(
            _GARAGE_SERVICE,
            endpoint_url=db_settings.GARAGE_ENDPOINT_URL,
            aws_access_key_id=db_settings.GARAGE_ACCESS_KEY,
            aws_secret_access_key=db_settings.GARAGE_SECRET_KEY,
            region_name=db_settings.GARAGE_REGION_NAME,
            config=garage_config,
        ) as client:
            yield client


async def check_connectivity(client: BaseClient) -> bool:
    """Verify bucket access using an injected request-scoped client."""
    await client.head_bucket(Bucket=db_settings.GARAGE_BUCKET_NAME)
    return True

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from sqlmodel import SQLModel

import app.api.routes.assets.model  # noqa: F401
import app.api.routes.debt.model  # noqa: F401
import app.api.routes.document.model  # noqa: F401
import app.api.routes.expense.model  # noqa: F401
import app.api.routes.family_expense.model  # noqa: F401
import app.api.routes.family.model  # noqa: F401
import app.api.routes.family_income.model  # noqa: F401
import app.api.routes.goals.model  # noqa: F401
import app.api.routes.insurance.model  # noqa: F401
import app.api.routes.savings.model  # noqa: F401
import app.api.routes.savings_plans.model  # noqa: F401
import app.api.routes.scheduler.model  # noqa: F401
import app.api.routes.transfer.model  # noqa: F401
import app.api.routes.friend.model  # noqa: F401
import app.api.routes.investments.model  # noqa: F401  (Plan 04)
import app.api.routes.currency.model  # noqa: F401  (Plan 10)
import app.core.funding_service  # noqa: F401  (Plan 01: payment_split_plans, payment_split_lines, funding_breakdown_entries)
import app.core.default_bucket_service  # noqa: F401  (Plan 01: default_bucket_entries)
# Old local auth tokens removed
from app.api.routes.user.model import UserBase, UserFamilyLink  # noqa: F401
from app.config import db_settings

config = context.config
config.set_main_option(
    "sqlalchemy.url", db_settings.POSTGRES_URL
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Render SQLModel's AutoString as plain sa.String() in generated migrations."""
    if type_ == "type" and obj.__class__.__name__ == "AutoString":
        autogen_context.imports.add("import sqlalchemy as sa")
        return "sa.String()"
    return False


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_item,
        version_table="alembic_version_fos",
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
        version_table="alembic_version_fos",
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

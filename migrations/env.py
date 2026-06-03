"""Alembic environment — async engine, URL + metadata from the app."""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import get_settings
from core.persistence.models import Base

config = context.config
target_metadata = Base.metadata


def _run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_settings().postgres_dsn)
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().postgres_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())

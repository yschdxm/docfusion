import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

engine = create_async_engine(
    settings.POSTGRES_URL.replace("postgresql://", "postgresql+asyncpg://"),
    echo=False,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_user_id_columns(conn)
    logger.info("PostgreSQL database initialized")


_USER_ID_TABLES = [
    "documents",
    "extraction_tasks",
    "table_fill_tasks",
    "conversations",
    "document_extractions",
    "template_usage_events",
]


async def _ensure_user_id_columns(conn):
    """幂等地为相关表添加 user_id 列和索引（向后兼容）"""
    for table in _USER_ID_TABLES:
        await conn.execute(text(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id UUID"
            f" REFERENCES users(id) ON DELETE CASCADE"
        ))
        await conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_user_id ON {table}(user_id)"
        ))
    logger.info("user_id columns ensured for all relevant tables")

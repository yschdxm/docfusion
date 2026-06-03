import logging
import os

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
        await _ensure_task_stats_column(conn)
        await _ensure_role_column(conn)
        await _ensure_is_shared_column(conn)
        await _ensure_selected_model_column(conn)
        await _ensure_super_admin(conn)
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


async def _ensure_task_stats_column(conn):
    """幂等地为 messages 表添加 task_stats 列（向后兼容）"""
    await conn.execute(text(
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS task_stats JSON"
    ))
    logger.info("task_stats column ensured for messages table")


async def _ensure_role_column(conn):
    """幂等地为 users 表添加 role 列（向后兼容）"""
    await conn.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user'"
    ))
    logger.info("role column ensured for users table")


async def _ensure_is_shared_column(conn):
    """幂等地为 documents 表添加 is_shared 列（向后兼容）"""
    await conn.execute(text(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE"
    ))
    logger.info("is_shared column ensured for documents table")


async def _ensure_selected_model_column(conn):
    """幂等地为 users 表添加 selected_model 列（向后兼容）"""
    await conn.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS selected_model VARCHAR(200)"
    ))
    logger.info("selected_model column ensured for users table")


async def _ensure_super_admin(conn):
    """确保系统中存在主管理员（super_admin），有且仅有一个"""
    result = await conn.execute(text("SELECT COUNT(*) FROM users WHERE role = 'super_admin'"))
    count = result.scalar()

    if count > 0:
        logger.info("Super admin already exists, skipping creation")
        return

    # 检查环境变量中是否配置了管理员账号
    admin_email = os.getenv("ADMIN_EMAIL", "").strip()
    admin_password = os.getenv("ADMIN_PASSWORD", "").strip()

    if admin_email and admin_password:
        # 使用环境变量配置的管理员账号
        from app.core.security import get_password_hash
        password_hash = get_password_hash(admin_password)

        # 检查用户是否存在
        result = await conn.execute(text("SELECT id FROM users WHERE email = :email"), {"email": admin_email})
        user = result.fetchone()

        if user:
            # 更新现有用户为super_admin
            await conn.execute(text(
                "UPDATE users SET role = 'super_admin' WHERE id = :id"
            ), {"id": user[0]})
            logger.info(f"Promoted existing user {admin_email} to super admin")
        else:
            # 创建新的super_admin用户
            import uuid
            from datetime import datetime
            user_id = uuid.uuid4()
            now = datetime.utcnow()
            await conn.execute(text(
                """INSERT INTO users (id, username, email, phone, password_hash, is_active, role, created_at, updated_at)
                   VALUES (:id, :username, :email, :phone, :password_hash, true, 'super_admin', :created_at, :updated_at)"""
            ), {
                "id": user_id,
                "username": "admin",
                "email": admin_email,
                "phone": "00000000000",
                "password_hash": password_hash,
                "created_at": now,
                "updated_at": now,
            })
            logger.info(f"Created super admin user with email {admin_email}")
    else:
        # 将第一个用户提升为super_admin
        result = await conn.execute(text(
            "SELECT id FROM users ORDER BY created_at ASC LIMIT 1"
        ))
        first_user = result.fetchone()

        if first_user:
            await conn.execute(text(
                "UPDATE users SET role = 'super_admin' WHERE id = :id"
            ), {"id": first_user[0]})
            logger.info(f"Promoted first user to super admin")
        else:
            logger.warning("No users found in database. Super admin will be created on first user registration.")

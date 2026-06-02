import logging
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)


class ConfigService:
    """系统配置服务，带内存缓存"""

    def __init__(self):
        self._cache: Dict[str, str] = {}
        self._cache_loaded = False

    async def get(self, db: AsyncSession, key: str, default: str = "") -> str:
        """获取配置值"""
        if not self._cache_loaded:
            await self._reload_cache(db)
        return self._cache.get(key, default)

    async def get_bool(self, db: AsyncSession, key: str, default: bool = True) -> bool:
        """获取布尔类型配置值"""
        val = await self.get(db, key, str(default).lower())
        return val.lower() in ("true", "1", "yes")

    async def get_int(self, db: AsyncSession, key: str, default: int = 0) -> int:
        """获取整数类型配置值"""
        val = await self.get(db, key, str(default))
        try:
            return int(val)
        except ValueError:
            return default

    async def set(self, db: AsyncSession, key: str, value: str, updated_by: Optional[UUID] = None, description: Optional[str] = None):
        """设置配置值（upsert）"""
        # 尝试更新
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()

        if config:
            config.value = value
            config.updated_by = updated_by
            if description:
                config.description = description
        else:
            config = SystemConfig(key=key, value=value, updated_by=updated_by, description=description)
            db.add(config)

        await db.commit()

        # 更新缓存
        self._cache[key] = value
        logger.info(f"Config updated: {key} = {value}")

    async def set_multiple(self, db: AsyncSession, configs: Dict[str, str], updated_by: Optional[UUID] = None):
        """批量设置配置值"""
        for key, value in configs.items():
            await self.set(db, key, value, updated_by)

    async def get_all(self, db: AsyncSession) -> list[SystemConfig]:
        """获取所有配置"""
        if not self._cache_loaded:
            await self._reload_cache(db)
        result = await db.execute(select(SystemConfig).order_by(SystemConfig.key))
        return result.scalars().all()

    async def _reload_cache(self, db: AsyncSession):
        """从数据库加载所有配置到缓存"""
        result = await db.execute(select(SystemConfig))
        configs = result.scalars().all()
        self._cache = {config.key: config.value for config in configs}
        self._cache_loaded = True
        logger.info(f"Config cache loaded with {len(self._cache)} entries")

    def invalidate_cache(self):
        """使缓存失效"""
        self._cache_loaded = False
        self._cache.clear()
        logger.info("Config cache invalidated")


# 全局配置服务实例
config_service = ConfigService()

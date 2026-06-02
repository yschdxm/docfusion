from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.auth import get_current_user
from app.db.postgres import get_db
from app.models.user import User

__all__ = ["get_current_user", "get_current_admin", "get_current_super_admin"]


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """检查当前用户是否为管理员（admin或super_admin）"""
    if current_user.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


async def get_current_super_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """检查当前用户是否为主管理员（super_admin）"""
    if current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="需要主管理员权限")
    return current_user

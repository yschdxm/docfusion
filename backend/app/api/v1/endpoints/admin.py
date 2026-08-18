import logging
from typing import Optional, List
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_current_admin, get_current_super_admin
from app.core.security import get_password_hash
from app.db.postgres import get_db
from app.models.document import Document
from app.models.user import User
from app.schemas.admin import (
    UserListItem,
    UserListResponse,
    UpdateUserRoleRequest,
    AdminUpdateUserRequest,
    BatchCreateUsersRequest,
    BatchCreateUserResult,
    BatchCreateUsersResponse,
    SystemConfigItem,
    UpdateSystemConfigRequest,
    RegistrationStatusResponse,
    SharedDocItem,
    SharedDocListResponse,
)
from app.services.config_service import config_service

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


class FetchModelsRequest(BaseModel):
    api_key: str
    base_url: str


class ModelInfo(BaseModel):
    id: str
    name: str


class FetchModelsResponse(BaseModel):
    models: List[ModelInfo]


# ==================== 用户管理 ====================

@router.get("/users", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表（支持分页、搜索、角色筛选）"""
    query = select(User)

    # 搜索条件
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                User.username.ilike(search_pattern),
                User.email.ilike(search_pattern),
                User.phone.ilike(search_pattern),
            )
        )

    # 角色筛选
    if role:
        query = query.where(User.role == role)

    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    # 分页
    query = query.order_by(User.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    users = result.scalars().all()

    return UserListResponse(
        users=[UserListItem.model_validate(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/users/batch", response_model=BatchCreateUsersResponse)
async def batch_create_users(
    payload: BatchCreateUsersRequest,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """批量创建账号：逐行校验，跳过冲突项，返回每行结果（不整体失败）

    - 密码缺省时使用 default_password，两者都没有则该行失败
    - 创建 admin 角色需要 super_admin 权限
    """
    if payload.role == "admin" and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="创建管理员账号需要主管理员权限")

    results: list[BatchCreateUserResult] = []
    to_add: list[User] = []
    seen_emails: set[str] = set()
    seen_phones: set[str] = set()

    for item in payload.users:
        username = item.username.strip()
        email = item.email.strip().lower()
        phone = item.phone.strip()
        password = item.password or payload.default_password

        if not password:
            results.append(BatchCreateUserResult(username=username, email=email, ok=False, error="缺少密码（行内与默认密码均为空）"))
            continue
        if email in seen_emails or phone in seen_phones:
            results.append(BatchCreateUserResult(username=username, email=email, ok=False, error="与本批次中前面的行重复"))
            continue
        existing = await db.execute(
            select(User).where(or_(User.email == email, User.phone == phone))
        )
        conflict = existing.scalars().first()
        if conflict:
            msg = "邮箱已注册" if conflict.email == email else "手机号已注册"
            results.append(BatchCreateUserResult(username=username, email=email, ok=False, error=msg))
            continue

        seen_emails.add(email)
        seen_phones.add(phone)
        to_add.append(User(
            username=username,
            email=email,
            phone=phone,
            password_hash=get_password_hash(password),
            role=payload.role,
        ))
        results.append(BatchCreateUserResult(username=username, email=email, ok=True))

    if to_add:
        db.add_all(to_add)
        await db.commit()
    created = sum(1 for r in results if r.ok)
    logger.info(f"[Admin] {current_user.username} 批量创建账号: 成功 {created}，失败 {len(results) - created}，角色 {payload.role}")
    return BatchCreateUsersResponse(created=created, failed=len(results) - created, results=results)


@router.get("/users/{user_id}")
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取用户详情（含文件列表）"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 获取用户的文档
    docs_result = await db.execute(
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(Document.created_at.desc())
    )
    documents = docs_result.scalars().all()

    return {
        "user": UserListItem.model_validate(user),
        "documents": [
            {
                "id": doc.id,
                "filename": doc.filename,
                "original_filename": doc.original_filename,
                "file_type": doc.file_type,
                "doc_category": doc.doc_category,
                "is_shared": doc.is_shared,
                "created_at": doc.created_at,
            }
            for doc in documents
        ],
    }


@router.put("/users/{user_id}")
async def update_user(
    user_id: UUID,
    payload: AdminUpdateUserRequest,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """编辑用户信息"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 不能修改自己的角色和状态
    if user_id == current_user.id:
        if payload.is_active is not None and not payload.is_active:
            raise HTTPException(status_code=400, detail="不能禁用自己的账号")

    # 更新字段
    if payload.username is not None:
        user.username = payload.username
    if payload.email is not None:
        # 检查邮箱唯一性
        existing = await db.execute(
            select(User).where(User.email == payload.email, User.id != user_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="邮箱已被使用")
        user.email = payload.email
    if payload.phone is not None:
        # 检查手机号唯一性
        existing = await db.execute(
            select(User).where(User.phone == payload.phone, User.id != user_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="手机号已被使用")
        user.phone = payload.phone
    if payload.password is not None:
        user.password_hash = get_password_hash(payload.password)
    if payload.is_active is not None:
        user.is_active = payload.is_active

    await db.commit()
    await db.refresh(user)

    return {"message": "用户信息已更新", "user": UserListItem.model_validate(user)}


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: UUID,
    payload: UpdateUserRoleRequest,
    current_user: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """修改用户角色（仅super_admin可操作）"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 不能修改自己的角色
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")

    # 不能修改其他super_admin的角色
    if user.role == "super_admin":
        raise HTTPException(status_code=403, detail="不能修改主管理员的角色")

    user.role = payload.role
    await db.commit()

    return {"message": f"用户角色已更新为 {payload.role}"}


# ==================== 系统配置 ====================

@router.get("/configs", response_model=list[SystemConfigItem])
async def get_configs(
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取所有系统配置"""
    configs = await config_service.get_all(db)
    return [SystemConfigItem.model_validate(c) for c in configs]


@router.put("/configs")
async def update_configs(
    payload: UpdateSystemConfigRequest,
    current_user: User = Depends(get_current_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新系统配置（仅super_admin可操作）"""
    await config_service.set_multiple(db, payload.configs, updated_by=current_user.id)

    # 如果更新了LLM相关配置，应用到LLM服务
    llm_config_keys = ["llm_providers", "llm_api_key", "llm_base_url", "llm_model", "llm_max_context_tokens", "llm_max_output_tokens"]
    if any(key in payload.configs for key in llm_config_keys) or any(key.startswith("llm_") for key in payload.configs):
        from app.services.llm_service import llm_service
        await llm_service.apply_db_config(db)

    # 如果更新了嵌入配置，应用到嵌入服务
    embedding_config_keys = ["embedding_api_key", "embedding_base_url", "embedding_model"]
    if any(key in payload.configs for key in embedding_config_keys):
        from app.services.embedding_service import embedding_service
        await embedding_service.apply_db_config(db)

    # 如果更新了重排配置，应用到重排服务
    rerank_config_keys = ["rerank_api_key", "rerank_base_url", "rerank_model"]
    if any(key in payload.configs for key in rerank_config_keys):
        from app.services.rerank_service import rerank_service
        await rerank_service.apply_db_config(db)

    # 如果更新了流控配置，应用到流控器
    rate_limit_keys = ["llm_rpm", "llm_tpm"]
    if any(key in payload.configs for key in rate_limit_keys):
        from app.core.rate_limiter import rate_limiter
        await rate_limiter.apply_db_config(db)

    return {"message": "配置已更新"}


@router.post("/configs/fetch-models", response_model=FetchModelsResponse)
async def fetch_models(
    payload: FetchModelsRequest,
    current_user: User = Depends(get_current_admin),
):
    """从OpenAI兼容API获取可用模型列表"""
    try:
        base_url = payload.base_url.rstrip("/")
        async with httpx.AsyncClient(verify=settings.SSL_VERIFY, timeout=30.0) as client:
            response = await client.get(
                f"{base_url}/models",
                headers={
                    "Authorization": f"Bearer {payload.api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("data", []):
                model_id = model.get("id", "")
                if model_id:
                    models.append(ModelInfo(id=model_id, name=model_id))

            return FetchModelsResponse(models=models)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=400, detail=f"API返回错误: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取模型列表失败: {str(e)}")
async def fetch_models(
    payload: FetchModelsRequest,
    current_user: User = Depends(get_current_admin),
):
    """从OpenAI兼容API获取可用模型列表"""
    try:
        base_url = payload.base_url.rstrip("/")
        async with httpx.AsyncClient(verify=settings.SSL_VERIFY, timeout=30.0) as client:
            response = await client.get(
                f"{base_url}/models",
                headers={
                    "Authorization": f"Bearer {payload.api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("data", []):
                model_id = model.get("id", "")
                if model_id:
                    models.append(ModelInfo(id=model_id, name=model_id))

            return FetchModelsResponse(models=models)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=400, detail=f"API返回错误: {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取模型列表失败: {str(e)}")


@router.get("/configs/registration", response_model=RegistrationStatusResponse)
async def check_registration(
    db: AsyncSession = Depends(get_db),
):
    """检查注册是否开放（公开接口）"""
    enabled = await config_service.get_bool(db, "registration_enabled", True)
    return RegistrationStatusResponse(enabled=enabled)


# ==================== 共享文档管理 ====================

@router.get("/shared-docs", response_model=SharedDocListResponse)
async def list_shared_docs(
    doc_category: Optional[str] = None,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取共享文档列表"""
    query = select(Document).where(Document.is_shared == True)

    if doc_category:
        query = query.where(Document.doc_category == doc_category)

    query = query.order_by(Document.created_at.desc())
    result = await db.execute(query)
    documents = result.scalars().all()

    return SharedDocListResponse(
        documents=[SharedDocItem.model_validate(d) for d in documents],
        total=len(documents),
    )


@router.post("/shared-docs/{doc_id}")
async def set_doc_shared(
    doc_id: UUID,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """设置文档为共享"""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    doc.is_shared = True
    await db.commit()

    return {"message": "文档已设置为共享"}


@router.delete("/shared-docs/{doc_id}")
async def remove_doc_shared(
    doc_id: UUID,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """取消文档共享"""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    doc.is_shared = False
    await db.commit()

    return {"message": "已取消文档共享"}

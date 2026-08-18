from datetime import datetime
from typing import Optional, Dict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: str
    phone: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    users: list[UserListItem]
    total: int
    page: int
    page_size: int


class UpdateUserRoleRequest(BaseModel):
    role: str = Field(pattern="^(user|admin)$")


class AdminUpdateUserRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=1, max_length=50)
    email: Optional[str] = Field(None, min_length=3, max_length=255)
    phone: Optional[str] = Field(None, min_length=11, max_length=20)
    password: Optional[str] = Field(None, min_length=6, max_length=128)
    is_active: Optional[bool] = None


class BatchCreateUserItem(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=3, max_length=255)
    phone: str = Field(min_length=11, max_length=20)
    password: Optional[str] = Field(None, min_length=6, max_length=128)  # 缺省用请求的 default_password


class BatchCreateUsersRequest(BaseModel):
    users: list[BatchCreateUserItem] = Field(min_length=1, max_length=200)
    default_password: Optional[str] = Field(None, min_length=6, max_length=128)
    role: str = Field(default="user", pattern="^(user|admin)$")


class BatchCreateUserResult(BaseModel):
    username: str
    email: str
    ok: bool
    error: Optional[str] = None


class BatchCreateUsersResponse(BaseModel):
    created: int
    failed: int
    results: list[BatchCreateUserResult]


class SystemConfigItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    description: Optional[str] = None
    updated_at: Optional[datetime] = None


class UpdateSystemConfigRequest(BaseModel):
    configs: Dict[str, str]


class RegistrationStatusResponse(BaseModel):
    enabled: bool


class SharedDocItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    original_filename: str
    file_type: str
    doc_category: str
    is_shared: bool
    user_id: Optional[UUID] = None
    created_at: datetime


class SharedDocListResponse(BaseModel):
    documents: list[SharedDocItem]
    total: int

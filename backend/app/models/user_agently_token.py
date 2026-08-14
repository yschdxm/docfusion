"""用户 Agently Token 模型"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.db.postgres import Base


class UserAgentlyToken(Base):
    """存储用户 Agently OAuth Token"""

    __tablename__ = "user_agently_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    # 设备授权下发的一对客户端凭证，刷新 token 时必须作为 client_id/client_secret 上送
    app_id = Column(String(255), nullable=True)
    app_secret = Column(Text, nullable=True)
    token_type = Column(String(50), default="Bearer", nullable=False)
    expires_at = Column(DateTime, nullable=True)
    email = Column(String(255), nullable=True)  # 授权的邮箱地址
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

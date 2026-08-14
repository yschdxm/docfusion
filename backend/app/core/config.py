import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache


def read_secret_from_file(file_path: str) -> str:
    """从 Docker secret 文件读取密钥"""
    try:
        with open(file_path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


class Settings(BaseSettings):
    APP_NAME: str = "DocFusion"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"

    # 日志级别配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_LEVEL_DB: str = os.getenv("LOG_LEVEL_DB", "WARNING")
    LOG_LEVEL_SERVICE: str = os.getenv("LOG_LEVEL_SERVICE", "INFO")
    LOG_LEVEL_API: str = os.getenv("LOG_LEVEL_API", "INFO")
    LOG_LEVEL_LLM: str = os.getenv("LOG_LEVEL_LLM", "INFO")
    LOG_LEVEL_KG: str = os.getenv("LOG_LEVEL_KG", "INFO")
    LOG_LEVEL_RAG: str = os.getenv("LOG_LEVEL_RAG", "INFO")
    LOG_LEVEL_UVICORN: str = os.getenv("LOG_LEVEL_UVICORN", "WARNING")
    LOG_LEVEL_SQLALCHEMY: str = os.getenv("LOG_LEVEL_SQLALCHEMY", "WARNING")
    LOG_LEVEL_NEO4J_DRIVER: str = os.getenv("LOG_LEVEL_NEO4J_DRIVER", "WARNING")

    # SECRET_KEY 是必需的
    SECRET_KEY: Optional[str] = None

    # Database
    POSTGRES_URL: Optional[str] = None
    NEO4J_URL: Optional[str] = None
    NEO4J_USER: Optional[str] = None
    NEO4J_PASSWORD: Optional[str] = None
    QDRANT_URL: Optional[str] = None

    # SSL Configuration
    SSL_VERIFY: bool = True  # 总开关，默认开启SSL验证

    # ONLYOFFICE
    ONLYOFFICE_SERVER_URL: str = "http://localhost:8088"
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"
    ONLYOFFICE_ENABLED: bool = False
    ONLYOFFICE_DOCUMENT_SERVER_URL: str = "http://localhost:8088"
    ONLYOFFICE_CALLBACK_BASE_URL: str = "http://host.docker.internal:8000"
    ONLYOFFICE_API_PREFIX: str = "/api/v1"
    ONLYOFFICE_PUBLIC_FILE_TTL_SECONDS: int = 900
    ONLYOFFICE_PUBLIC_SIGNING_SECRET: Optional[str] = None

    # SMTP Mail
    SMTP_SERVER: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""

    # Tencent Agent Mail / agently-cli
    AGENTLY_CLI_BIN: str = "agently-cli"
    AGENTLY_MAIL_LIST_COMMAND: str = ""
    AGENTLY_MAIL_DETAIL_COMMAND: str = ""
    AGENTLY_MAIL_SEND_COMMAND: str = ""
    AGENTLY_MAIL_ATTACHMENT_COMMAND: str = ""
    # 注意必须小于前置网关（Cloudflare ~100s）的超时，否则网关会先截断响应，
    # 客户端只能看到网关的 502 页面而拿不到后端的错误信息
    AGENTLY_MAIL_TIMEOUT_SECONDS: int = 90

    # Agently OAuth 配置（通过 agently-cli 处理，通常不需要修改）
    AGENTLY_OAUTH_LOGOUT_URL: str = "https://auth.agent.qq.com/oauth/logout_session"

    # File Storage
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 52428800

    # 用户隔离
    INCLUDE_ORPHAN_DATA: bool = True  # 是否允许查看无主文档（user_id为NULL的旧数据）

    class Config:
        # .env 文件在项目根目录，相对于 backend 目录
        env_file = "../.env"
        # 忽略未定义的字段（兼容旧的环境变量）
        extra = "ignore"

    @model_validator(mode="after")
    def validate_required_fields(self):
        """验证所有必需字段都已设置"""
        required_fields = {
            "SECRET_KEY": "用于会话加密和令牌签名",
            "POSTGRES_URL": "PostgreSQL 数据库连接",
            "NEO4J_URL": "Neo4j 图数据库连接",
            "NEO4J_USER": "Neo4j 用户名",
            "NEO4J_PASSWORD": "Neo4j 密码",
            "QDRANT_URL": "Qdrant 向量数据库连接",
        }

        missing_fields = []
        for field_name, description in required_fields.items():
            value = getattr(self, field_name)
            if not value or not value.strip():
                missing_fields.append(f"{field_name} ({description})")

        if missing_fields:
            error_msg = "以下必需的环境变量未设置或为空：\n"
            for field in missing_fields:
                error_msg += f"  - {field}\n"
            error_msg += "\n请检查 .env 文件或环境变量配置。"
            raise ValueError(error_msg)

        return self

    def model_post_init(self, __context):
        """在模型初始化后，处理 Docker secrets"""
        pass


@lru_cache()
def get_settings():
    return Settings()

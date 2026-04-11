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

    # MiMO API
    MIMO_API_KEY: Optional[str] = None
    MIMO_BASE_URL: str = "https://api.xiaomimimo.com/v1"
    MIMO_MODEL: str = "mimo-v2-flash"

    # LLM 流控配置
    LLM_RPM: int = 100  # 每分钟最大请求数
    LLM_TPM: int = 10_000_000  # 每分钟最大 token 数 (10M)

    # Gitee AI API
    GITEE_AI_API_KEY: Optional[str] = None
    GITEE_AI_BASE_URL: str = "https://ai.gitee.com/v1"
    EMBEDDING_MODEL: str = "bge-m3"
    RERANK_MODEL: str = "bge-reranker-v2-m3"

    # SSL Configuration
    SSL_VERIFY: bool = True  # 总开关，默认开启SSL验证
    SSL_VERIFY_MIMO: bool = True  # MiMO模型SSL验证
    SSL_VERIFY_GITEE_AI: bool = True  # Gitee AI（嵌入和重排模型）SSL验证

    # File Storage
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 52428800

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
            "MIMO_API_KEY": "MiMO 模型 API 密钥",
            "GITEE_AI_API_KEY": "Gitee AI API 密钥（用于嵌入和重排模型）",
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
        # 如果环境变量中没有设置 API 密钥，尝试从 Docker secret 文件读取
        if not self.MIMO_API_KEY:
            secret_file = os.getenv("MIMO_API_KEY_FILE", "")
            if secret_file:
                self.MIMO_API_KEY = read_secret_from_file(secret_file)

        if not self.GITEE_AI_API_KEY:
            secret_file = os.getenv("GITEE_AI_API_KEY_FILE", "")
            if secret_file:
                self.GITEE_AI_API_KEY = read_secret_from_file(secret_file)


@lru_cache()
def get_settings():
    return Settings()

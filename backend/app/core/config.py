from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "DocFusion"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    SECRET_KEY: str = "docfusion-secret-key-2024"
    
    # Database
    POSTGRES_URL: str = "postgresql://docfusion:docfusion123@localhost:5432/docfusion"
    MONGODB_URL: str = "mongodb://localhost:27017/docfusion"
    NEO4J_URL: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4j123"
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # MiMO API
    MIMO_API_KEY: str = "sk-cnp5q8ys4bj0xmked6o0913fyq6jzjt1cs5o5ucxik57a49q"
    MIMO_BASE_URL: str = "https://api.xiaomimimo.com/v1"
    MIMO_MODEL: str = "mimo-v2-flash"
    
    # File Storage
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()

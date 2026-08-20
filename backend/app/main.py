import logging
import os
import ipaddress

from app.core.logging import setup_logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.api.v1.api import api_router
from app.db.postgres import init_db
from app.db.neo4j_db import init_neo4j, close_neo4j

# 导入所有模型以确保 create_all 能创建所有表
from app.models import user, document, system_config

setup_logging()

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting up")
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

    await init_db()
    await init_neo4j()

    # 初始化系统配置（如果不存在则创建默认值）
    from app.services.config_service import config_service
    from app.services.llm_service import llm_service
    from app.services.embedding_service import embedding_service
    from app.services.rerank_service import rerank_service
    from app.core.rate_limiter import rate_limiter
    from app.db.postgres import async_session

    async with async_session() as db:
        # 确保注册开关配置存在
        reg_enabled = await config_service.get(db, "registration_enabled")
        if not reg_enabled:
            await config_service.set(db, "registration_enabled", "true", description="是否开放注册")

        # 从数据库应用LLM配置
        await llm_service.apply_db_config(db)

        # 从数据库应用嵌入和重排配置
        await embedding_service.apply_db_config(db)
        await rerank_service.apply_db_config(db)

        # 从数据库应用流控配置
        await rate_limiter.apply_db_config(db)

    yield

    logger.info("Application shutting down")
    await close_neo4j()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# 信任的主机名，防止 Host 头攻击
# 支持环境变量 ALLOWED_HOSTS，格式: host1,192.168.2.0/24,172.16.0.0/12
# 支持精确主机名和 CIDR 网段
_allowed_hosts_raw = os.getenv("ALLOWED_HOSTS", "*")
if _allowed_hosts_raw == "*":
    _allowed_hosts = ["*"]
    _allowed_networks = []
else:
    _allowed_hosts = []
    _allowed_networks = []
    for item in [h.strip() for h in _allowed_hosts_raw.split(",")]:
        if "/" in item:
            _allowed_networks.append(ipaddress.ip_network(item, strict=False))
        else:
            _allowed_hosts.append(item)


class TrustedHostMiddleware(BaseHTTPMiddleware):
    """支持 CIDR 网段的 Host 白名单中间件"""

    async def dispatch(self, request: Request, call_next):
        if "*" in (_allowed_hosts if not _allowed_networks else ["*"]):
            return await call_next(request)
        host = request.headers.get("host", "").split(":")[0]
        if host in _allowed_hosts:
            return await call_next(request)
        try:
            ip = ipaddress.ip_address(host)
            if any(ip in net for net in _allowed_networks):
                return await call_next(request)
        except ValueError:
            pass
        logger.warning("Rejected request from untrusted host: %s", host)
        return Response(status_code=400, content="Invalid host header")


app.add_middleware(TrustedHostMiddleware)

# 注意：不在此处加 GZipMiddleware —— starlette 0.38 的流式 gzip 不按块 flush，
# 会缓冲 SSE（Agent 流式对话）。JSON 压缩由前端 nginx 的 gzip_proxied 统一处理。

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"message": "DocFusion API", "version": settings.APP_VERSION}


@app.get("/health")
async def health():
    return {"status": "ok"}

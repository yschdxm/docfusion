from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from app.core.config import get_settings
from app.api.v1.api import api_router
from app.db.postgres import init_db
from app.db.mongodb import init_mongodb, close_mongodb
from app.db.neo4j_db import init_neo4j, close_neo4j

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(os.path.join(settings.UPLOAD_DIR, "output"), exist_ok=True)
    
    await init_db()
    await init_mongodb()
    await init_neo4j()
    
    yield
    
    await close_mongodb()
    await close_neo4j()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan
)

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

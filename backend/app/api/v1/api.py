from fastapi import APIRouter
from app.api.v1.endpoints import documents, extraction, table_fill, knowledge, agent, conversations

api_router = APIRouter()

api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(extraction.router, prefix="/extraction", tags=["extraction"])
api_router.include_router(table_fill.router, prefix="/table-fill", tags=["table-fill"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])

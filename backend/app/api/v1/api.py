from fastapi import APIRouter
from app.api.v1.endpoints import documents, knowledge, agent, conversations, agent_stream

api_router = APIRouter()

api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_router.include_router(agent_stream.router, prefix="/agent", tags=["agent-stream"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])

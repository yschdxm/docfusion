from fastapi import APIRouter
from app.api.v1.endpoints import documents, knowledge, agent, conversations, agent_stream, auth, table_fill, admin, interaction, fill_table_plugin

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_router.include_router(agent_stream.router, prefix="/agent", tags=["agent-stream"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
api_router.include_router(table_fill.router, prefix="/table-fill", tags=["table-fill"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(interaction.router, prefix="/interaction", tags=["interaction"])
api_router.include_router(fill_table_plugin.router, prefix="/fill-table-plugin", tags=["fill-table-plugin"])

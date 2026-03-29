from fastapi import APIRouter, HTTPException
from typing import List
from app.schemas.knowledge import (
    KnowledgeQueryRequest,
    KnowledgeGraphResponse,
    KnowledgeQueryResponse
)
from app.services.knowledge_graph_service import knowledge_graph_service

router = APIRouter()


@router.get("/graph", response_model=KnowledgeGraphResponse)
async def get_knowledge_graph(limit: int = 100):
    try:
        graph_data = await knowledge_graph_service.get_graph(limit=limit)
        return KnowledgeGraphResponse(
            nodes=graph_data.get("nodes", []),
            edges=graph_data.get("edges", [])
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query", response_model=KnowledgeQueryResponse)
async def query_knowledge_graph(request: KnowledgeQueryRequest):
    try:
        result = await knowledge_graph_service.query_graph(request.query)
        return KnowledgeQueryResponse(
            answer=result.get("answer", ""),
            related_nodes=[
                {"id": e["name"], "name": e["name"], "type": e["type"], "value": e.get("value", "")}
                for e in result.get("related_entities", [])
            ],
            related_edges=[]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

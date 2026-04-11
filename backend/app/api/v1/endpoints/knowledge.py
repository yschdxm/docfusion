from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from app.schemas.knowledge import (
    KnowledgeQueryRequest,
    KnowledgeGraphResponse,
    KnowledgeQueryResponse
)
from app.services.knowledge_graph_service import knowledge_graph_service

router = APIRouter()


@router.get("/graph", response_model=KnowledgeGraphResponse)
async def get_knowledge_graph(
    limit: int = 500,
    document_id: Optional[str] = Query(None, description="按文档ID过滤图谱数据")
):
    try:
        graph_data = await knowledge_graph_service.get_graph(limit=limit, document_id=document_id)
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

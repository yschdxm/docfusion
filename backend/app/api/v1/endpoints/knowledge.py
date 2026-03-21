from fastapi import APIRouter, HTTPException
from typing import List
from app.schemas.knowledge import (
    KnowledgeBuildRequest,
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
                {"id": e["name"], "name": e["name"], "type": e["type"], "properties": e}
                for e in result.get("related_entities", [])
            ],
            related_edges=[]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/build")
async def build_knowledge_graph(request: KnowledgeBuildRequest):
    try:
        return {
            "message": "知识图谱构建任务已启动",
            "file_ids": request.file_ids
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities")
async def list_graph_entities(entity_type: str = None, limit: int = 50):
    try:
        from app.db.neo4j_db import run_cypher
        
        if entity_type:
            query = """
                MATCH (e:Entity {type: $type})
                RETURN e.name AS name, e.type AS type, e.value AS value
                LIMIT $limit
            """
            params = {"type": entity_type, "limit": limit}
        else:
            query = """
                MATCH (e:Entity)
                RETURN e.name AS name, e.type AS type, e.value AS value
                LIMIT $limit
            """
            params = {"limit": limit}
        
        result = await run_cypher(query, params)
        
        return {
            "entities": [
                {"name": r["name"], "type": r["type"], "value": r.get("value", "")}
                for r in result
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/relations")
async def list_graph_relations(limit: int = 50):
    try:
        from app.db.neo4j_db import run_cypher
        
        result = await run_cypher(
            """
            MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity)
            RETURN a.name AS source, b.name AS target, r.type AS type, r.description AS description
            LIMIT $limit
            """,
            {"limit": limit}
        )
        
        return {
            "relations": [
                {
                    "source": r["source"],
                    "target": r["target"],
                    "type": r["type"],
                    "description": r.get("description", "")
                }
                for r in result
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cross-references")
async def find_cross_references(doc_ids: List[str]):
    try:
        result = await knowledge_graph_service.find_document_relations(doc_ids)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.deps import get_current_user
from app.db.postgres import get_db
from app.models.document import Document
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeQueryRequest,
    KnowledgeGraphResponse,
    KnowledgeQueryResponse
)
from app.services.knowledge_graph_service import knowledge_graph_service

router = APIRouter()


async def _get_user_doc_ids(user_id, db: AsyncSession) -> List[str]:
    """获取当前用户的所有文档ID列表"""
    result = await db.execute(
        select(Document.id).where(Document.user_id == user_id)
    )
    return [str(row[0]) for row in result.all()]


@router.get("/graph", response_model=KnowledgeGraphResponse)
async def get_knowledge_graph(
    limit: int = 500,
    document_id: Optional[str] = Query(None, description="按文档ID过滤图谱数据"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        # 如果指定了文档ID，验证归属
        if document_id:
            doc_result = await db.execute(
                select(Document).where(
                    Document.id == document_id,
                    Document.user_id == current_user.id
                )
            )
            if not doc_result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="文档不存在")
            user_doc_ids = None  # 指定了 document_id，不需要额外过滤
        else:
            user_doc_ids = await _get_user_doc_ids(current_user.id, db)

        graph_data = await knowledge_graph_service.get_graph(
            limit=limit,
            document_id=document_id,
            user_doc_ids=user_doc_ids
        )
        return KnowledgeGraphResponse(
            nodes=graph_data.get("nodes", []),
            edges=graph_data.get("edges", [])
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query", response_model=KnowledgeQueryResponse)
async def query_knowledge_graph(
    request: KnowledgeQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        user_doc_ids = await _get_user_doc_ids(current_user.id, db)
        result = await knowledge_graph_service.query_graph(
            request.query,
            user_doc_ids=user_doc_ids
        )
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

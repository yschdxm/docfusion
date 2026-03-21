from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse
from typing import List, Optional
from uuid import UUID, uuid4
import os
import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.core.config import get_settings
from app.db.postgres import get_db
from app.models.document import Document, Entity, ExtractionTask
from app.schemas.document import (
    DocumentResponse,
    DocumentOperateRequest,
    DocumentOperateResponse
)
from app.services.document_agent import document_agent
from app.services.knowledge_graph_service import knowledge_graph_service
from app.db.mongodb import get_collection
from app.db.neo4j_db import run_cypher

settings = get_settings()
router = APIRouter()


@router.post("/upload", response_model=List[DocumentResponse])
async def upload_documents(
    files: List[UploadFile] = File(...),
    doc_category: str = "source",
    db: AsyncSession = Depends(get_db)
):
    uploaded_docs = []
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    
    for file in files:
        file_ext = file.filename.split(".")[-1].lower()
        if file_ext not in ["docx", "xlsx", "md", "txt"]:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_ext}")
        
        unique_filename = f"{uuid4().hex}.{file_ext}"
        file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)
        
        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)
        
        doc = Document(
            filename=unique_filename,
            original_filename=file.filename,
            file_type=file_ext,
            doc_category=doc_category,
            file_size=len(content),
            file_path=file_path,
            status="uploaded"
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        
        uploaded_docs.append(doc)
    
    return uploaded_docs


@router.get("/", response_model=List[DocumentResponse])
async def list_documents(
    doc_category: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    query = select(Document)
    if doc_category:
        query = query.where(Document.doc_category == doc_category)
    result = await db.execute(
        query.offset(skip).limit(limit).order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{document_id}")
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{document_id}/download")
async def download_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    return FileResponse(
        doc.file_path,
        filename=doc.original_filename,
        media_type="application/octet-stream"
    )


@router.post("/operate", response_model=DocumentOperateResponse)
async def operate_document(
    request: DocumentOperateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == request.file_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    try:
        operation_result = await document_agent.process_instruction(
            file_path=doc.file_path,
            file_type=doc.file_type,
            instruction=request.instruction,
            output_format=request.output_format
        )
        
        task_id = uuid4()
        
        return DocumentOperateResponse(
            task_id=task_id,
            status="completed",
            result=operation_result,
            message=operation_result.get("message", "操作完成")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    # 查询文档
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc_id_str = str(document_id)
    
    try:
        # 1. 删除 PostgreSQL 中的实体数据
        await db.execute(delete(Entity).where(Entity.document_id == document_id))
        
        # 2. 删除提取任务记录（可选，保留历史记录也可以）
        await db.execute(delete(ExtractionTask).where(ExtractionTask.id == document_id))
        
        # 3. 删除 Neo4j 中的知识图谱节点
        try:
            await run_cypher(
                """
                MATCH (e:Entity {document_id: $doc_id})
                DETACH DELETE e
                """,
                {"doc_id": doc_id_str}
            )
            # 同时删除 Document 节点
            await run_cypher(
                """
                MATCH (d:Document {id: $doc_id})
                DETACH DELETE d
                """,
                {"doc_id": doc_id_str}
            )
        except Exception as e:
            print(f"Neo4j delete error: {e}")
        
        # 4. 删除 MongoDB 中的提取结果
        try:
            collection = get_collection("extractions")
            if collection:
                await collection.delete_one({"document_id": doc_id_str})
        except Exception as e:
            print(f"MongoDB delete error: {e}")
        
        # 5. 删除物理文件
        if doc.file_path and os.path.exists(doc.file_path):
            os.remove(doc.file_path)
        
        # 6. 删除数据库记录
        await db.delete(doc)
        await db.commit()
        
        return {"message": "文档及相关数据已删除", "document_id": document_id}
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")

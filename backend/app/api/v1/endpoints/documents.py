from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse
from typing import List, Optional
from uuid import UUID, uuid4
import os
import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.db.postgres import get_db
from app.models.document import Document
from app.schemas.document import (
    DocumentResponse,
    DocumentOperateRequest,
    DocumentOperateResponse
)
from app.services.document_agent import document_agent
from app.services.knowledge_graph_service import knowledge_graph_service
from sqlalchemy import select

settings = get_settings()
router = APIRouter()


@router.post("/upload", response_model=List[DocumentResponse])
async def upload_documents(
    files: List[UploadFile] = File(...),
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
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Document).offset(skip).limit(limit).order_by(Document.created_at.desc())
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
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    
    await db.delete(doc)
    await db.commit()
    
    return {"message": "Document deleted"}

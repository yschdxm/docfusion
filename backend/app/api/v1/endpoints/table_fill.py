from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from typing import List
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.postgres import get_db
from app.models.document import Document, TableFillTask
from app.schemas.table_fill import TableFillRequest, TableFillResponse
from app.services.table_filling_service import table_filling_service
from datetime import datetime
import os

router = APIRouter()


@router.post("/fill", response_model=TableFillResponse)
async def fill_table(
    request: TableFillRequest,
    db: AsyncSession = Depends(get_db)
):
    task = TableFillTask(
        template_file_id=request.template_file_id,
        source_file_ids=[str(fid) for fid in request.source_file_ids],
        user_instruction=request.user_instruction,
        status="processing"
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    
    try:
        source_files = []
        for file_id in request.source_file_ids:
            result = await db.execute(select(Document).where(Document.id == file_id))
            doc = result.scalar_one_or_none()
            if doc:
                source_files.append({
                    "file_type": doc.file_type,
                    "file_path": doc.file_path
                })
        
        result = await db.execute(
            select(Document).where(Document.id == request.template_file_id)
        )
        template_doc = result.scalar_one_or_none()
        if not template_doc:
            raise HTTPException(status_code=404, detail="Template file not found")
        
        template_file = {
            "file_type": template_doc.file_type,
            "file_path": template_doc.file_path
        }
        
        if template_doc.file_type == "xlsx":
            fill_result = await table_filling_service.fill_table(
                source_files=source_files,
                template_file=template_file,
                user_instruction=request.user_instruction
            )
        else:
            fill_result = await table_filling_service.fill_word_template(
                source_files=source_files,
                template_file=template_file,
                user_instruction=request.user_instruction
            )
        
        # 保存填写结果为 output 类型的文档
        filled_doc = Document(
            filename=fill_result["output_filename"],
            original_filename=f"filled_{template_doc.original_filename}",
            file_type="xlsx" if template_doc.file_type == "xlsx" else "docx",
            doc_category="output",  # 输出类型，不是源文档
            file_path=fill_result["output_path"],
            status="completed"
        )
        db.add(filled_doc)
        
        task.status = "completed"
        task.filled_file_path = fill_result["output_path"]
        task.result = fill_result.get("filled_data", {})
        task.completed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(filled_doc)
        
        return TableFillResponse(
            task_id=task.id,
            status="completed",
            filled_file_id=filled_doc.id,
            filled_file_url=f"/api/v1/table-fill/download/{filled_doc.id}",
            message="表格填写完成",
            result=fill_result.get("filled_data", {})
        )
    except Exception as e:
        task.status = "failed"
        task.result = {"error": str(e)}
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{file_id}")
async def download_filled_table(
    file_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Document).where(Document.id == file_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        doc.file_path,
        filename=doc.original_filename,
        media_type="application/octet-stream"
    )


@router.get("/output-files")
async def list_output_files(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """列出所有输出文件（填写结果）"""
    result = await db.execute(
        select(Document)
        .where(Document.doc_category == "output")
        .offset(skip)
        .limit(limit)
        .order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@router.get("/download-file/{filename}")
async def download_filled_file(filename: str):
    file_path = os.path.join("./uploads/output", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/octet-stream"
    )


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(TableFillTask).where(TableFillTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return {
        "task_id": task.id,
        "status": task.status,
        "result": task.result,
        "created_at": task.created_at,
        "completed_at": task.completed_at
    }

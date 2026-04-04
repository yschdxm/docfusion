import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update as sql_update
from app.db.postgres import get_db, async_session
from app.models.document import Document, TableFillTask
from app.schemas.table_fill import TableFillRequest, TableFillResponse
from app.services.table_filling_service import table_filling_service
from datetime import datetime

logger = logging.getLogger(__name__)
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
        status="processing",
        result={
            "progress": "0%",
            "current_step": "准备中...",
            "total_files": len(request.source_file_ids),
            "processed_files": 0
        }
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    
    # 进度回调函数
    async def update_progress(message: str, progress: str = None):
        try:
            async with async_session() as progress_db:
                current_result = task.result or {}
                current_result.update({
                    "current_step": message,
                    "progress": progress or current_result.get("progress", "0%"),
                    "updated_at": datetime.utcnow().isoformat()
                })
                stmt = sql_update(TableFillTask).where(
                    TableFillTask.id == task.id
                ).values(result=current_result)
                await progress_db.execute(stmt)
                await progress_db.commit()
        except Exception as e:
            logger.error("Progress update error: %s", e)
    
    try:
        await update_progress("正在加载源文档...", "10%")
        
        source_files = []
        for idx, file_id in enumerate(request.source_file_ids):
            result = await db.execute(select(Document).where(Document.id == file_id))
            doc = result.scalar_one_or_none()
            if doc:
                source_files.append({
                    "file_type": doc.file_type,
                    "file_path": doc.file_path
                })
                await update_progress(f"已加载文档 {idx + 1}/{len(request.source_file_ids)}", f"{20 + int((idx / len(request.source_file_ids)) * 20)}%")
        
        await update_progress("正在加载模板...", "40%")
        
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
        
        await update_progress("正在分析模板结构...", "50%")

        doc_ids = [str(fid) for fid in request.source_file_ids]

        if template_doc.file_type == "xlsx":
            await update_progress("正在填写Excel表格...", "60%")
            fill_result = await table_filling_service.fill_table(
                source_files=source_files,
                template_file=template_file,
                user_instruction=request.user_instruction,
                doc_ids=doc_ids,
            )
        else:
            await update_progress("正在填写Word文档...", "60%")
            fill_result = await table_filling_service.fill_word_template(
                source_files=source_files,
                template_file=template_file,
                user_instruction=request.user_instruction,
                doc_ids=doc_ids,
            )
        
        await update_progress("正在保存结果...", "90%")
        
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
        await db.commit()
        await db.refresh(filled_doc)  # 先 refresh 获取 ID
        
        task.status = "completed"
        task.filled_file_path = fill_result["output_path"]
        task.result = {
            "progress": "100%",
            "current_step": "完成",
            "filled_doc_id": str(filled_doc.id),
            **fill_result.get("filled_data", {})
        }
        task.completed_at = datetime.utcnow()
        await db.commit()
        
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
        task.result = {"error": str(e), "progress": "100%", "current_step": f"失败: {str(e)}"}
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
    safe_dir = Path("./uploads/output").resolve()
    file_path = (safe_dir / filename).resolve()
    if not str(file_path).startswith(str(safe_dir)):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        str(file_path),
        filename=filename,
        media_type="application/octet-stream"
    )


@router.get("/tasks", response_model=List[dict])
async def list_tasks(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    # 获取所有文档的ID和名称映射
    docs_result = await db.execute(
        select(Document.id, Document.original_filename)
    )
    doc_map = {str(doc.id): doc.original_filename for doc in docs_result.all()}
    
    # 获取任务列表
    result = await db.execute(
        select(TableFillTask)
        .order_by(TableFillTask.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    tasks = result.scalars().all()
    
    task_list = []
    for task in tasks:
        # 获取模板名称
        template_name = doc_map.get(str(task.template_file_id), "未知模板")
        
        # 获取源文件名称
        source_names = []
        if task.source_file_ids:
            for file_id in task.source_file_ids:
                name = doc_map.get(file_id, "未知文件")
                source_names.append(name)
        
        # 获取进度信息和 filled_doc_id
        progress = "0%"
        current_step = ""
        filled_doc_id = None
        if task.result and isinstance(task.result, dict):
            progress = task.result.get("progress", "0%")
            current_step = task.result.get("current_step", "")
            filled_doc_id = task.result.get("filled_doc_id")
        
        # 优化的时间预测算法
        estimated_time = None
        if task.status == "processing" and task.created_at:
            elapsed = (datetime.utcnow() - task.created_at).total_seconds()
            if progress and progress != "0%":
                try:
                    progress_num = int(progress.replace("%", ""))
                    if progress_num > 0 and progress_num < 100:
                        # 基于进度的线性预测
                        estimated_seconds = (elapsed / progress_num) * (100 - progress_num)
                        
                        # 格式化输出
                        if estimated_seconds < 60:
                            estimated_time = f"约 {int(estimated_seconds)} 秒"
                        elif estimated_seconds < 3600:
                            minutes = int(estimated_seconds // 60)
                            seconds = int(estimated_seconds % 60)
                            estimated_time = f"约 {minutes} 分 {seconds} 秒"
                        else:
                            hours = int(estimated_seconds // 3600)
                            minutes = int((estimated_seconds % 3600) // 60)
                            estimated_time = f"约 {hours} 时 {minutes} 分"
                except:
                    pass
        
        # 构建下载 URL
        if filled_doc_id and filled_doc_id != "None":
            filled_file_url = f"/api/v1/table-fill/download/{filled_doc_id}"
        else:
            filled_file_url = None
            filled_doc_id = None  # 重置为 None
        
        task_list.append({
            "id": str(task.id),
            "status": task.status,
            "source_files": task.source_file_ids or [],
            "source_names": source_names,
            "template_name": template_name,
            "filled_file_id": filled_doc_id,
            "filled_file_url": filled_file_url,
            "progress": progress,
            "current_step": current_step,
            "estimated_time": estimated_time,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "error": task.result.get("error") if task.result and isinstance(task.result, dict) else None
        })
    
    return task_list


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(TableFillTask).where(TableFillTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 从result中获取filled_doc_id
    filled_doc_id = None
    if task.result and isinstance(task.result, dict):
        filled_doc_id = task.result.get("filled_doc_id")
    
    return {
        "task_id": str(task.id),
        "status": task.status,
        "result": task.result,
        "filled_doc_id": filled_doc_id,
        "error": task.result.get("error") if task.result else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None
    }

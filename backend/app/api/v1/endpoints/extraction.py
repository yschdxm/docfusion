from fastapi import APIRouter, HTTPException, Depends
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.postgres import get_db
from app.models.document import Document, ExtractionTask
from datetime import datetime

router = APIRouter()


@router.get("/tasks", response_model=List[dict])
async def list_tasks(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    docs_result = await db.execute(
        select(Document.id, Document.original_filename)
    )
    doc_map = {str(doc.id): doc.original_filename for doc in docs_result.all()}
    
    result = await db.execute(
        select(ExtractionTask)
        .order_by(ExtractionTask.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    tasks = result.scalars().all()
    
    task_list = []
    for task in tasks:
        file_names = []
        if task.input_files:
            for file_id in task.input_files:
                name = doc_map.get(file_id, "未知文件")
                file_names.append(name)
        
        entities_count = 0
        progress = "0%"
        current_step = ""
        if task.result and isinstance(task.result, dict):
            entities_count = task.result.get("entities_count", 0)
            progress = task.result.get("progress", "0%")
            current_step = task.result.get("current_step", "")
        
        estimated_time = None
        if task.status == "processing" and task.started_at:
            elapsed = (datetime.utcnow() - task.started_at).total_seconds()
            if progress and progress != "0%":
                try:
                    progress_num = int(progress.replace("%", ""))
                    if progress_num > 0 and progress_num < 100:
                        estimated_seconds = (elapsed / progress_num) * (100 - progress_num)
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
        
        task_list.append({
            "id": str(task.id),
            "status": task.status,
            "file_ids": task.input_files or [],
            "file_names": file_names,
            "entities_count": entities_count,
            "progress": progress,
            "current_step": current_step,
            "estimated_time": estimated_time,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "error": task.error_message
        })
    
    return task_list

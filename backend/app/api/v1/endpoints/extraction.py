from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update as sql_update
from app.db.postgres import get_db, engine
from app.models.document import Document, ExtractionTask, Entity
from app.schemas.extraction import ExtractionRequest, ExtractionResponse, EntityInfo
from app.services.extraction_service import extraction_service
from app.services.knowledge_graph_service import knowledge_graph_service
from datetime import datetime

router = APIRouter()


@router.post("/extract", response_model=ExtractionResponse)
async def extract_information(
    request: ExtractionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    task = ExtractionTask(
        task_type="entity_extraction",
        status="processing",
        input_files=[str(fid) for fid in request.file_ids],
        config={
            "entity_types": request.entity_types,
            "custom_fields": request.custom_fields
        },
        result={
            "progress": "0%",
            "current_step": "准备中...",
            "total_files": len(request.file_ids),
            "processed_files": 0
        },
        started_at=datetime.utcnow()
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    
    all_entities = []
    errors = []
    total_files = len(request.file_ids)
    
    # 创建进度回调函数
    async def update_progress(message: str, progress: str = None):
        try:
            # 使用新的会话来更新进度，确保立即提交
            async with AsyncSession(engine) as progress_db:
                current_result = task.result or {}
                current_result.update({
                    "current_step": message,
                    "progress": progress or current_result.get("progress", "0%"),
                    "updated_at": datetime.utcnow().isoformat()
                })
                stmt = sql_update(ExtractionTask).where(
                    ExtractionTask.id == task.id
                ).values(result=current_result)
                await progress_db.execute(stmt)
                await progress_db.commit()
        except Exception as e:
            print(f"Progress update error: {e}")
    
    try:
        for idx, file_id in enumerate(request.file_ids):
            result = await db.execute(select(Document).where(Document.id == file_id))
            doc = result.scalar_one_or_none()
            if not doc:
                errors.append(f"文档 {file_id} 不存在")
                continue
            
            # 计算当前文件的进度范围
            file_progress_start = int((idx / total_files) * 100)
            file_progress_range = int(100 / total_files)
            
            # 更新进度
            await update_progress(
                f"正在处理文档 {idx + 1}/{total_files}: {doc.original_filename}",
                f"{file_progress_start}%"
            )
            
            try:
                extraction_result = await extraction_service.extract_from_document(
                    file_path=doc.file_path,
                    file_type=doc.file_type,
                    entity_types=request.entity_types,
                    custom_fields=request.custom_fields,
                    progress_callback=update_progress,
                    base_progress=file_progress_start,
                    progress_range=file_progress_range
                )
                
                for entity_data in extraction_result.get("entities", []):
                    entity = Entity(
                        document_id=doc.id,
                        entity_type=entity_data.get("entity_type", "UNKNOWN"),
                        entity_name=entity_data.get("entity_name", ""),
                        entity_value=entity_data.get("entity_value", ""),
                        context=entity_data.get("context", "")
                    )
                    db.add(entity)
                    all_entities.append(entity_data)
                
                await extraction_service.save_to_mongodb(doc.id, extraction_result)
                
                background_tasks.add_task(
                    knowledge_graph_service.build_graph_from_entities,
                    str(doc.id),
                    extraction_result.get("entities", [])
                )
            except Exception as doc_error:
                error_msg = f"处理文档 {doc.original_filename} 时出错: {str(doc_error)}"
                errors.append(error_msg)
                print(error_msg)
                continue
        
        await db.commit()
        
        # 更新任务状态
        if errors and not all_entities:
            task.status = "failed"
            task.error_message = "; ".join(errors)
            task.result = {"progress": "100%", "error": "; ".join(errors)}
        elif errors:
            task.status = "completed"
            task.result = {
                "entities_count": len(all_entities),
                "warnings": errors,
                "progress": "100%",
                "processed_files": total_files
            }
        else:
            task.status = "completed"
            task.result = {
                "entities_count": len(all_entities),
                "progress": "100%",
                "processed_files": total_files
            }
        
        task.completed_at = datetime.utcnow()
        await db.commit()
        
        return ExtractionResponse(
            task_id=task.id,
            status=task.status,
            entities=all_entities,
            message=f"成功提取 {len(all_entities)} 个实体" + (f"，{len(errors)} 个错误" if errors else "")
        )
    except Exception as e:
        task.status = "failed"
        task.error_message = str(e)
        task.result = {"progress": "100%", "error": str(e)}
        task.completed_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities", response_model=List[EntityInfo])
async def list_entities(
    document_id: UUID = None,
    entity_type: str = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    query = select(Entity)
    
    if document_id:
        query = query.where(Entity.document_id == document_id)
    if entity_type:
        query = query.where(Entity.entity_type == entity_type)
    
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


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
        select(ExtractionTask)
        .order_by(ExtractionTask.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    tasks = result.scalars().all()
    
    task_list = []
    for task in tasks:
        # 获取文件名
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
        
        # 优化的时间预测算法
        estimated_time = None
        if task.status == "processing" and task.started_at:
            elapsed = (datetime.utcnow() - task.started_at).total_seconds()
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


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(ExtractionTask).where(ExtractionTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return {
        "task_id": task.id,
        "status": task.status,
        "result": task.result,
        "error_message": task.error_message,
        "created_at": task.created_at,
        "completed_at": task.completed_at
    }

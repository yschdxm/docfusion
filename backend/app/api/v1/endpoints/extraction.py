from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.postgres import get_db
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
        started_at=datetime.utcnow()
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    
    all_entities = []
    errors = []
    
    try:
        for file_id in request.file_ids:
            result = await db.execute(select(Document).where(Document.id == file_id))
            doc = result.scalar_one_or_none()
            if not doc:
                errors.append(f"文档 {file_id} 不存在")
                continue
            
            try:
                extraction_result = await extraction_service.extract_from_document(
                    file_path=doc.file_path,
                    file_type=doc.file_type,
                    entity_types=request.entity_types,
                    custom_fields=request.custom_fields
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
            # 全部失败
            task.status = "failed"
            task.error_message = "; ".join(errors)
        elif errors:
            # 部分成功
            task.status = "completed"
            task.result = {
                "entities_count": len(all_entities),
                "warnings": errors
            }
        else:
            # 全部成功
            task.status = "completed"
            task.result = {"entities_count": len(all_entities)}
        
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
        if task.result and isinstance(task.result, dict):
            entities_count = task.result.get("entities_count", 0)
        
        task_list.append({
            "id": str(task.id),
            "status": task.status,
            "file_ids": task.input_files or [],
            "file_names": file_names,
            "entities_count": entities_count,
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

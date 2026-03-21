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
    
    try:
        for file_id in request.file_ids:
            result = await db.execute(select(Document).where(Document.id == file_id))
            doc = result.scalar_one_or_none()
            if not doc:
                continue
            
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
        
        await db.commit()
        
        task.status = "completed"
        task.result = {"entities_count": len(all_entities)}
        task.completed_at = datetime.utcnow()
        await db.commit()
        
        return ExtractionResponse(
            task_id=task.id,
            status="completed",
            entities=all_entities,
            message=f"成功提取 {len(all_entities)} 个实体"
        )
    except Exception as e:
        task.status = "failed"
        task.error_message = str(e)
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

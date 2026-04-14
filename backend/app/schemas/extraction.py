from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class ExtractionRequest(BaseModel):
    file_ids: List[UUID]
    entity_types: Optional[List[str]] = None
    custom_fields: Optional[List[str]] = None


class ExtractionResponse(BaseModel):
    task_id: UUID
    status: str
    entities: List[Dict[str, Any]] = []
    relations: List[Dict[str, Any]] = []
    message: Optional[str] = None


class EntityInfo(BaseModel):
    id: UUID
    document_id: UUID
    entity_type: str
    entity_name: str
    entity_value: Optional[str]
    context: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

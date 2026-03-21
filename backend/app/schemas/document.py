from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class DocumentBase(BaseModel):
    filename: str
    file_type: str


class DocumentCreate(DocumentBase):
    pass


class DocumentResponse(DocumentBase):
    id: UUID
    original_filename: str
    file_size: Optional[int]
    status: str
    metadata_info: Dict[str, Any] = {}
    created_at: datetime
    
    class Config:
        from_attributes = True


class DocumentOperateRequest(BaseModel):
    file_id: UUID
    instruction: str
    output_format: Optional[str] = None


class DocumentOperateResponse(BaseModel):
    task_id: UUID
    status: str
    result: Optional[Dict[str, Any]] = None
    message: Optional[str] = None

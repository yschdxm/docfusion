from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class DocumentBase(BaseModel):
    filename: str
    file_type: str
    doc_category: str = "source"


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




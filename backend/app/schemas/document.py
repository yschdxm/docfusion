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
    root_document_id: Optional[UUID] = None
    version: int = 1
    origin_type: Optional[str] = None
    origin_label: Optional[str] = None
    origin_conversation_id: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentPreviewResponse(BaseModel):
    file_name: str
    file_type: str
    preview_type: str
    content: str = ""
    html_content: Optional[str] = None
    truncated: bool = False
    can_edit: bool = False
    sheets: Optional[List[Dict[str, Any]]] = None


class DocumentSaveRequest(BaseModel):
    content: str




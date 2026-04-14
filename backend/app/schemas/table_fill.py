from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class TableFillRequest(BaseModel):
    source_file_ids: List[UUID]
    template_file_id: UUID
    user_instruction: str


class TableFillResponse(BaseModel):
    task_id: UUID
    status: str
    filled_file_id: Optional[UUID] = None
    filled_file_url: Optional[str] = None
    message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None

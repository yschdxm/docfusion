import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, BigInteger, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from app.db.postgres import Base


class Document(Base):
    __tablename__ = "documents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)  # docx, xlsx, md, txt
    doc_category = Column(String(20), default="source")  # source, template
    file_size = Column(BigInteger)
    file_path = Column(String(500))
    status = Column(String(20), default="pending")
    metadata_info = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExtractionTask(Base):
    __tablename__ = "extraction_tasks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type = Column(String(50), nullable=False)
    status = Column(String(20), default="pending")
    input_files = Column(JSON, default=[])
    config = Column(JSON, default={})
    result = Column(JSON, default={})
    error_message = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class TableFillTask(Base):
    __tablename__ = "table_fill_tasks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_file_id = Column(UUID(as_uuid=True))
    source_file_ids = Column(JSON, default=[])
    user_instruction = Column(Text)
    status = Column(String(20), default="pending")
    filled_file_path = Column(String(500))
    result = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)


class Entity(Base):
    __tablename__ = "entities"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True))
    entity_type = Column(String(50), nullable=False)
    entity_name = Column(String(500), nullable=False)
    entity_value = Column(Text)
    context = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

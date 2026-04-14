import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.postgres import Base


class Document(Base):
    __tablename__ = 'documents'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)  # docx, xlsx, md, txt
    doc_category = Column(String(20), default='source')  # source, template, output
    file_size = Column(BigInteger)
    file_path = Column(String(500))
    status = Column(String(20), default='pending')
    metadata_info = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExtractionTask(Base):
    __tablename__ = 'extraction_tasks'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type = Column(String(50), nullable=False)
    status = Column(String(20), default='pending')
    input_files = Column(JSON, default=[])
    config = Column(JSON, default={})
    result = Column(JSON, default={})
    error_message = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class TableFillTask(Base):
    __tablename__ = 'table_fill_tasks'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_file_id = Column(UUID(as_uuid=True))
    source_file_ids = Column(JSON, default=[])
    user_instruction = Column(Text)
    status = Column(String(20), default='pending')
    filled_file_path = Column(String(500))
    result = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)


class Conversation(Base):
    __tablename__ = 'conversations'

    id = Column(String(50), primary_key=True)  # chat-xxx
    title = Column(String(255), default='新对话')
    file_ids = Column(JSON, default=[])
    template_id = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Message(Base):
    __tablename__ = 'messages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(50), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    action_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TemplateUsageEvent(Base):
    __tablename__ = 'template_usage_events'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey('documents.id'), nullable=False, index=True)
    template_name = Column(String(255), nullable=False)
    source_file_count = Column(Integer, default=0)
    output_file_id = Column(UUID(as_uuid=True), nullable=True)
    used_at = Column(DateTime, default=datetime.utcnow, index=True)

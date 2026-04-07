import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, BigInteger, JSON, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from app.db.postgres import Base


class Document(Base):
    __tablename__ = "documents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)  # docx, xlsx, md, txt
    doc_category = Column(String(20), default="source")  # source, template, output
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


class Conversation(Base):
    """对话会话表"""
    __tablename__ = "conversations"
    
    id = Column(String(50), primary_key=True)  # chat-xxx 格式
    title = Column(String(255), default="新对话")
    file_ids = Column(JSON, default=[])  # 选中的文档ID列表
    template_id = Column(String(50), nullable=True)  # 选中的模板ID
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Message(Base):
    """对话消息表"""
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(50), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    action_data = Column(JSON, nullable=True)  # 操作卡片数据
    created_at = Column(DateTime, default=datetime.utcnow)

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, BigInteger, JSON, Text, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.postgres import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
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
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
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
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
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
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
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
    steps = Column(JSON, nullable=True)  # Agent 执行步骤
    task_stats = Column(JSON, nullable=True)  # 任务统计（token用量、耗时等）
    created_at = Column(DateTime, default=datetime.utcnow)


class DocumentExtraction(Base):
    """文档提取结果表"""
    __tablename__ = "document_extractions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    document_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    entities_count = Column(Integer, default=0)
    relations_count = Column(Integer, default=0)
    chunks_count = Column(Integer, default=0)
    xlsx_schema = Column(JSON, default=[])  # 存储 xlsx 表结构信息
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TemplateUsageEvent(Base):
    __tablename__ = 'template_usage_events'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    template_id = Column(UUID(as_uuid=True), ForeignKey('documents.id'), nullable=False, index=True)
    template_name = Column(String(255), nullable=False)
    source_file_count = Column(Integer, default=0)
    output_file_id = Column(UUID(as_uuid=True), nullable=True)
    used_at = Column(DateTime, default=datetime.utcnow, index=True)

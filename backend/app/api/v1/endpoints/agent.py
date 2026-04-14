from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.postgres import get_db
from app.models.document import Document
from app.services.agent_service import agent_service
from app.services.document_agent import document_agent
from app.services.llm_service import llm_service
from pydantic import BaseModel
import logging
import os

logger = logging.getLogger(__name__)
router = APIRouter()
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
PROJECT_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))


def _get_file_media_type(file_type: str) -> str:
    media_types = {
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xls": "application/vnd.ms-excel",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "ppt": "application/vnd.ms-powerpoint",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "txt": "text/plain; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "csv": "text/csv; charset=utf-8",
    }
    return media_types.get((file_type or "").lower(), "application/octet-stream")


def _resolve_document_path(file_path: str | None) -> str | None:
    if not file_path:
        return None

    normalized = os.path.normpath(file_path)
    candidates: list[str] = []

    if os.path.isabs(normalized):
        candidates.append(normalized)
    else:
        trimmed = normalized.lstrip(".\\/")
        candidates.extend(
            [
                os.path.abspath(normalized),
                os.path.abspath(os.path.join(BACKEND_ROOT, normalized)),
                os.path.abspath(os.path.join(BACKEND_ROOT, trimmed)),
                os.path.abspath(os.path.join(PROJECT_ROOT, normalized)),
                os.path.abspath(os.path.join(PROJECT_ROOT, trimmed)),
            ]
        )

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.exists(candidate):
            return candidate

    return candidates[0] if candidates else None


class AgentChatRequest(BaseModel):
    message: str
    file_ids: List[UUID] = []
    template_id: Optional[UUID] = None
    conversation_history: List[Dict[str, str]] = []
    action_confirmed: bool = False
    action_id: Optional[str] = None


class AgentAction(BaseModel):
    action_id: str
    action_type: str
    title: str
    description: str
    progress: Optional[int] = None
    result: Optional[Dict[str, Any]] = None


class AgentChatResponse(BaseModel):
    message: str
    action: Optional[AgentAction] = None


async def get_documents_content(
    file_ids: List[UUID],
    db: AsyncSession
) -> List[Dict[str, Any]]:
    """获取文档内容"""
    from app.services.document_processor import DocxParser, XlsxParser, MdParser, TxtParser
    parsers = {
        "docx": DocxParser(),
        "xlsx": XlsxParser(),
        "md": MdParser(),
        "txt": TxtParser()
    }
    
    documents = []
    for doc_id in file_ids:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if doc:
            try:
                parser = parsers.get(doc.file_type)
                resolved_path = _resolve_document_path(doc.file_path)
                if parser:
                    if not resolved_path or not os.path.exists(resolved_path):
                        raise FileNotFoundError(f"Document file not found: {doc.file_path}")
                    parsed = parser.parse(resolved_path)
                    documents.append({
                        "id": str(doc.id),
                        "filename": doc.original_filename,
                        "file_type": doc.file_type,
                        "file_path": resolved_path,
                        "doc_category": doc.doc_category,
                        "content": parsed.get("full_text", "")
                    })
            except Exception as e:
                logger.error(f"文档解析失败: {doc_id}, error={e}")
    return documents


async def get_template_content(
    template_id: UUID,
    db: AsyncSession
) -> Optional[Dict[str, Any]]:
    """获取模板内容"""
    from app.services.document_processor import DocxParser, XlsxParser
    parsers = {"docx": DocxParser(), "xlsx": XlsxParser()}
    
    result = await db.execute(select(Document).where(Document.id == template_id))
    template_doc = result.scalar_one_or_none()
    if not template_doc:
        return None
    
    try:
        parser = parsers.get(template_doc.file_type)
        resolved_path = _resolve_document_path(template_doc.file_path)
        if parser:
            if not resolved_path or not os.path.exists(resolved_path):
                raise FileNotFoundError(f"Template file not found: {template_doc.file_path}")
            parsed = parser.parse(resolved_path)
            return {
                "filename": template_doc.original_filename,
                "file_type": template_doc.file_type,
                "file_path": resolved_path,
                "content": parsed.get("full_text", "")
            }
    except Exception as e:
        logger.error(f"模板解析失败: {template_id}, error={e}")
    return None


def convert_agent_result_to_response(result: Dict[str, Any]) -> AgentChatResponse:
    """将document_agent的结果转换为AgentChatResponse"""
    action = None
    if "action" in result and result["action"]:
        action_data = result["action"]
        action = AgentAction(
            action_id=action_data.get("action_id", ""),
            action_type=action_data.get("action_type", ""),
            title=action_data.get("title", ""),
            description=action_data.get("description", ""),
            progress=action_data.get("progress"),
            result=action_data.get("result")
        )
    return AgentChatResponse(
        message=result.get("message", "操作完成"),
        action=action
    )


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    db: AsyncSession = Depends(get_db)
):
    """智能体对话接口"""
    
    documents_content = []
    if request.file_ids:
        documents_content = await get_documents_content(request.file_ids, db)
    
    template_content = None
    template_info = None
    if request.template_id:
        template_content = await get_template_content(request.template_id, db)
        if template_content:
            template_info = {"filename": template_content["filename"], "file_type": template_content["file_type"]}
    
    documents_info = [{"filename": d["filename"], "file_type": d["file_type"]} for d in documents_content]
    
    if request.action_confirmed and request.action_id:
        result = await document_agent.process_instruction(
            intent="",
            documents_content=documents_content,
            template_content=template_content,
            action_id=request.action_id
        )
        return convert_agent_result_to_response(result)
    
    intent_result = await agent_service.analyze_intent(
        user_message=request.message,
        documents_info=documents_info,
        template_info=template_info
    )
    
    intent = intent_result.get("intent", "chat")
    need_confirm = intent_result.get("need_confirm", False)
    confirm_message = intent_result.get("confirm_message", "")
    
    if intent == "chat":
        reply = await agent_service.chat_response(
            user_message=request.message,
            conversation_history=request.conversation_history,
            documents_content=documents_content if documents_content else None,
            template_content=template_content
        )
        return AgentChatResponse(message=reply)
    
    elif intent == "query_content":
        if not documents_content and not template_content:
            return AgentChatResponse(message="请先选择要查询的文档或模板。")
        summary = await agent_service.summarize_documents(
            documents_content=documents_content,
            template_content=template_content
        )
        return AgentChatResponse(message=summary)
    
    elif intent == "fill_table":
        if not documents_content:
            return AgentChatResponse(message="请先选择源文档。")
        if not template_content:
            return AgentChatResponse(message="请先选择一个模板文件，然后再进行表格填写。")
        
        if need_confirm:
            action_id = f"fill-{uuid4().hex[:8]}"
            return AgentChatResponse(
                message=confirm_message or "我将使用选中的文档数据填写模板表格。",
                action=AgentAction(
                    action_id=action_id,
                    action_type="confirm_fill",
                    title="表格填写确认",
                    description=f"将使用 {len(documents_content)} 个文档的数据填写模板。"
                )
            )
        else:
            result = await document_agent.process_instruction(
                intent="fill_table",
                documents_content=documents_content,
                template_content=template_content
            )
            return convert_agent_result_to_response(result)
    
    elif intent == "operation":
        return AgentChatResponse(message="文档操作功能正在开发中，敬请期待。")
    
    return AgentChatResponse(message="我不太理解您的意思，请换一种方式描述。")


class GenerateTitleRequest(BaseModel):
    message: str


@router.post("/generate-title")
async def generate_title(request: GenerateTitleRequest):
    """轻量接口：根据用户消息生成对话标题"""
    try:
        prompt = f"请用10个字以内总结以下问题的标题，只返回标题内容，不要返回其他任何内容。\n问题：{request.message[:50]}"
        title = await llm_service.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=50
        )
        return {"title": title.strip()[:10]}
    except Exception as e:
        return {"title": "新对话"}


@router.get("/download-file/{filename}")
async def download_generated_file(filename: str):
    resolved_path = _resolve_document_path(os.path.join("./uploads/output", filename))
    if not resolved_path or not os.path.exists(resolved_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        resolved_path,
        filename=filename,
        media_type=_get_file_media_type(os.path.splitext(filename)[1].lstrip(".")),
    )

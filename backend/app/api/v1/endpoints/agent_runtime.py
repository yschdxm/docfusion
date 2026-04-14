import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.postgres import get_db
from app.models.document import Document
from app.services.agent_service import agent_service
from app.services.document_agent import document_agent
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


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


async def get_documents_content(file_ids: List[UUID], db: AsyncSession) -> List[Dict[str, Any]]:
    from app.services.document_processor import DocxParser, MdParser, TxtParser, XlsxParser

    parsers = {
        "docx": DocxParser(),
        "xlsx": XlsxParser(),
        "md": MdParser(),
        "txt": TxtParser(),
    }

    documents = []
    for doc_id in file_ids:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc:
            continue
        try:
            parser = parsers.get(doc.file_type)
            if not parser:
                continue
            parsed = parser.parse(doc.file_path)
            documents.append(
                {
                    "id": str(doc.id),
                    "filename": doc.original_filename,
                    "file_type": doc.file_type,
                    "file_path": doc.file_path,
                    "doc_category": doc.doc_category,
                    "content": parsed.get("full_text", ""),
                }
            )
        except Exception as exc:
            logger.error("Document parse failed: doc_id=%s error=%s", doc_id, exc)
    return documents


async def get_template_content(template_id: UUID, db: AsyncSession) -> Optional[Dict[str, Any]]:
    from app.services.document_processor import DocxParser, XlsxParser

    parsers = {"docx": DocxParser(), "xlsx": XlsxParser()}
    result = await db.execute(select(Document).where(Document.id == template_id))
    template_doc = result.scalar_one_or_none()
    if not template_doc:
        return None

    try:
        parser = parsers.get(template_doc.file_type)
        if not parser:
            return None
        parsed = parser.parse(template_doc.file_path)
        return {
            "filename": template_doc.original_filename,
            "file_type": template_doc.file_type,
            "file_path": template_doc.file_path,
            "content": parsed.get("full_text", ""),
        }
    except Exception as exc:
        logger.error("Template parse failed: template_id=%s error=%s", template_id, exc)
        return None


def convert_agent_result_to_response(result: Dict[str, Any]) -> AgentChatResponse:
    action = None
    action_data = result.get("action")
    if action_data:
        action = AgentAction(
            action_id=action_data.get("action_id", ""),
            action_type=action_data.get("action_type", ""),
            title=action_data.get("title", ""),
            description=action_data.get("description", ""),
            progress=action_data.get("progress"),
            result=action_data.get("result"),
        )
    return AgentChatResponse(message=result.get("message", "操作完成"), action=action)


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(request: AgentChatRequest, db: AsyncSession = Depends(get_db)):
    documents_content = []
    if request.file_ids:
        documents_content = await get_documents_content(request.file_ids, db)

    template_content = None
    template_info = None
    if request.template_id:
        template_content = await get_template_content(request.template_id, db)
        if template_content:
            template_info = {
                "filename": template_content["filename"],
                "file_type": template_content["file_type"],
            }

    documents_info = [{"filename": item["filename"], "file_type": item["file_type"]} for item in documents_content]

    if request.action_confirmed and request.action_id:
        result = await document_agent.process_instruction(
            intent="",
            documents_content=documents_content,
            template_content=template_content,
            action_id=request.action_id,
        )
        return convert_agent_result_to_response(result)

    intent_result = await agent_service.analyze_intent(
        user_message=request.message,
        documents_info=documents_info,
        template_info=template_info,
    )

    intent = intent_result.get("intent", "chat")
    need_confirm = intent_result.get("need_confirm", False)
    confirm_message = intent_result.get("confirm_message", "")

    if intent == "chat":
        reply = await agent_service.chat_response(
            user_message=request.message,
            conversation_history=request.conversation_history,
            documents_content=documents_content if documents_content else None,
            template_content=template_content,
        )
        return AgentChatResponse(message=reply)

    if intent == "query_content":
        if not documents_content and not template_content:
            return AgentChatResponse(message="请先选择要查询的文档或模板。")
        summary = await agent_service.summarize_documents(
            documents_content=documents_content,
            template_content=template_content,
        )
        return AgentChatResponse(message=summary)

    if intent == "fill_table":
        if not documents_content:
            return AgentChatResponse(message="请先选择源文档。")
        if not template_content:
            return AgentChatResponse(message="请先选择一个模板文件，然后再进行表格填写。")
        if need_confirm:
            action_id = f"fill-{uuid4().hex[:8]}"
            return AgentChatResponse(
                message=confirm_message or "将使用选中文档的数据填写模板。",
                action=AgentAction(
                    action_id=action_id,
                    action_type="confirm_fill",
                    title="表格填写确认",
                    description=f"将使用 {len(documents_content)} 个文档的数据填写模板。",
                ),
            )
        result = await document_agent.process_instruction(
            intent="fill_table",
            documents_content=documents_content,
            template_content=template_content,
        )
        return convert_agent_result_to_response(result)

    if intent == "operation":
        if not documents_content:
            return AgentChatResponse(message="请先选择要操作的文档。")
        result = await document_agent.process_instruction(
            intent="operation",
            documents_content=documents_content,
            instruction=request.message,
        )
        return convert_agent_result_to_response(result)

    return AgentChatResponse(message="我没有理解你的意图，请换一种表述。")


class GenerateTitleRequest(BaseModel):
    message: str


@router.post("/generate-title")
async def generate_title(request: GenerateTitleRequest):
    try:
        prompt = f"请用 10 个字以内概括这个问题的标题，只返回标题：{request.message[:50]}"
        title = await llm_service.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=50,
        )
        return {"title": title.strip()[:10]}
    except Exception:
        return {"title": "新对话"}


@router.get("/download-file/{filename}")
async def download_generated_file(filename: str):
    file_path = os.path.join(settings.UPLOAD_DIR, "output", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/octet-stream",
    )

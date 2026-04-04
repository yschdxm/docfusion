from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, update as sql_update
from app.db.postgres import get_db, engine
from app.models.document import Document, TableFillTask
from app.services.agent_service import agent_service
from app.services.document_agent import document_agent
from app.services.llm_service import llm_service
from pydantic import BaseModel
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class AgentChatRequest(BaseModel):
    message: str
    file_ids: List[UUID] = []
    template_id: Optional[UUID] = None
    conversation_history: List[Dict[str, str]] = []
    action_confirmed: bool = False
    action_id: Optional[str] = None
    task_id: Optional[str] = None  # 任务ID，用于更新现有任务


class AgentAction(BaseModel):
    action_id: str
    action_type: str
    title: str
    description: str
    progress: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    task_id: Optional[str] = None  # 任务ID，用于查询任务状态


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
                if parser:
                    parsed = parser.parse(doc.file_path)
                    documents.append({
                        "id": str(doc.id),
                        "filename": doc.original_filename,
                        "file_type": doc.file_type,
                        "file_path": doc.file_path,
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
        if parser:
            parsed = parser.parse(template_doc.file_path)
            return {
                "filename": template_doc.original_filename,
                "file_type": template_doc.file_type,
                "file_path": template_doc.file_path,
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
            result=action_data.get("result"),
            task_id=action_data.get("task_id")
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

    logger.debug("[AGENT] action_confirmed=%s, action_id=%s, intent_result=None yet",
                  request.action_confirmed, request.action_id)

    if request.action_confirmed and request.action_id:
        logger.debug("[AGENT] 走 action_confirmed 分支, action_id=%s", request.action_id)
        # 查找现有的pending任务
        task = None
        
        # 如果提供了task_id，直接查找
        if request.task_id:
            try:
                task_uuid = UUID(request.task_id)
                result = await db.execute(
                    select(TableFillTask).where(TableFillTask.id == task_uuid)
                )
                task = result.scalar_one_or_none()
            except ValueError:
                pass
        
        # 如果没有找到，查找最近的pending任务
        if not task:
            result = await db.execute(
                select(TableFillTask)
                .where(TableFillTask.status == "pending")
                .order_by(TableFillTask.created_at.desc())
                .limit(1)
            )
            task = result.scalar_one_or_none()
        
        if task and task.status == "pending":
            # 更新现有任务状态
            task.status = "processing"
            task.result = {
                "progress": "0%",
                "current_step": "准备中...",
                "source": "agent"
            }
        else:
            # 创建新任务
            task = TableFillTask(
                template_file_id=request.template_id,
                source_file_ids=[str(fid) for fid in request.file_ids],
                user_instruction=request.message or "智能填写表格",
                status="processing",
                result={
                    "progress": "0%",
                    "current_step": "准备中...",
                    "source": "agent"
                }
            )
            db.add(task)
        
        await db.commit()
        await db.refresh(task)
        
        # 更新进度函数
        async def update_progress(message: str, progress: str = None):
            try:
                async with AsyncSession(engine) as progress_db:
                    current_result = task.result or {}
                    current_result.update({
                        "current_step": message,
                        "progress": progress or current_result.get("progress", "0%"),
                        "updated_at": datetime.utcnow().isoformat()
                    })
                    stmt = sql_update(TableFillTask).where(
                        TableFillTask.id == task.id
                    ).values(result=current_result)
                    await progress_db.execute(stmt)
                    await progress_db.commit()
            except Exception as e:
                logger.error(f"Progress update error: {e}")
        
        try:
            await update_progress("正在执行表格填写...", "10%")
            
            result = await document_agent.process_instruction(
                intent="",
                documents_content=documents_content,
                template_content=template_content,
                action_id=request.action_id
            )
            
            if result.get("success"):
                # 获取填写结果
                action_result = result.get("action", {}).get("result", {})
                output_path = action_result.get("output_path", "")
                output_filename = action_result.get("output_filename", "")
                
                # 创建Document记录保存填写结果
                if output_path and output_filename:
                    filled_doc = Document(
                        filename=output_filename,
                        original_filename=f"filled_{template_content.get('filename', 'template') if template_content else 'template'}",
                        file_type=output_filename.split(".")[-1] if "." in output_filename else "xlsx",
                        doc_category="output",
                        file_path=output_path,
                        status="completed"
                    )
                    db.add(filled_doc)
                    await db.flush()
                    
                    # 更新任务状态
                    await update_progress("完成", "100%")
                    task.status = "completed"
                    task.filled_file_path = output_path
                    task.result = {
                        "progress": "100%",
                        "current_step": "完成",
                        "source": "agent",
                        "filled_doc_id": str(filled_doc.id),
                        "entities_used": action_result.get("entities_used", 0)
                    }
                    task.completed_at = datetime.utcnow()
                    
                    # 更新返回结果中的下载URL
                    if result.get("action") and result["action"].get("result"):
                        result["action"]["result"]["filled_file_url"] = f"/api/v1/table-fill/download/{filled_doc.id}"
                        result["action"]["result"]["filled_file_id"] = str(filled_doc.id)
                else:
                    await update_progress("完成", "100%")
                    task.status = "completed"
                    task.result = {
                        "progress": "100%",
                        "current_step": "完成",
                        "source": "agent"
                    }
                    task.completed_at = datetime.utcnow()
            else:
                await update_progress(f"失败: {result.get('message', '')}", "100%")
                task.status = "failed"
                task.result = {
                    "progress": "100%",
                    "current_step": f"失败: {result.get('message', '')}",
                    "source": "agent",
                    "error": result.get("message", "")
                }
                task.completed_at = datetime.utcnow()
            
            await db.commit()
            
            # 添加task_id到结果中
            if result.get("action"):
                result["action"]["task_id"] = str(task.id)
            
            return convert_agent_result_to_response(result)
        except Exception as e:
            await update_progress(f"失败: {str(e)}", "100%")
            task.status = "failed"
            task.result = {
                "progress": "100%",
                "current_step": f"失败: {str(e)}",
                "source": "agent",
                "error": str(e)
            }
            task.completed_at = datetime.utcnow()
            await db.commit()
            raise
    
    intent_result = await agent_service.analyze_intent(
        user_message=request.message,
        documents_info=documents_info,
        template_info=template_info
    )
    
    intent = intent_result.get("intent", "chat")
    need_confirm = intent_result.get("need_confirm", False)
    confirm_message = intent_result.get("confirm_message", "")

    logger.debug("[AGENT] 意图分析结果: intent=%s, need_confirm=%s", intent, need_confirm)
    
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
        if not template_content:
            return AgentChatResponse(message="请先选择一个模板文件，然后再进行表格填写。")
        
        # 如果没有选择文档，使用RAG自动选择
        use_auto_fill = len(documents_content) == 0
        
        if need_confirm:
            # 预先创建任务
            task = TableFillTask(
                template_file_id=request.template_id,
                source_file_ids=[str(fid) for fid in request.file_ids],
                user_instruction=request.message or "智能填写表格",
                status="pending",
                result={
                    "progress": "0%",
                    "current_step": "等待确认...",
                    "source": "agent"
                }
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)
            
            action_id = f"fill-{uuid4().hex[:8]}"
            if use_auto_fill:
                desc = "将自动查找相关文档并填写模板。"
                confirm_msg = "我将自动查找相关文档并填写模板。"
            else:
                desc = f"将使用 {len(documents_content)} 个文档的数据填写模板。"
                confirm_msg = confirm_message or "我将使用选中的文档数据填写模板表格。"
            
            return AgentChatResponse(
                message=confirm_msg,
                action=AgentAction(
                    action_id=action_id,
                    action_type="confirm_fill",
                    title="表格填写确认",
                    description=desc,
                    task_id=str(task.id)
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

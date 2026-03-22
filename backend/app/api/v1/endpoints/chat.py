from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from app.services.llm_service import llm_service
from app.db.mongodb import get_collection

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    session_id: Optional[str] = None
    document_ids: Optional[List[str]] = None


class ChatResponse(BaseModel):
    message: str
    session_id: str


@router.post("/completion", response_model=ChatResponse)
async def chat_completion(request: ChatRequest):
    try:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        
        if request.document_ids:
            context_parts = []
            collection = get_collection("document_contents")
            
            # MiMo-V2-Flash 支持 256K 上下文
            for doc_id in request.document_ids:
                doc_content = await collection.find_one({"document_id": doc_id})
                if doc_content:
                    context_parts.append(
                        f"Document {doc_id}:\n{doc_content.get('raw_content', '')[:50000]}"
                    )
            
            if context_parts:
                context = "\n\n---\n\n".join(context_parts)
                system_msg = {
                    "role": "system",
                    "content": f"你是一个文档分析助手。以下是相关文档内容，请基于这些内容回答用户的问题。\n\n{context}"
                }
                messages.insert(0, system_msg)
        
        response = await llm_service.chat_completion(messages, temperature=0.7)
        
        if request.session_id:
            collection = get_collection("conversation_history")
            await collection.update_one(
                {"session_id": request.session_id},
                {
                    "$push": {
                        "messages": {
                            "$each": [
                                {"role": "user", "content": request.messages[-1].content},
                                {"role": "assistant", "content": response}
                            ]
                        }
                    }
                },
                upsert=True
            )
        
        return ChatResponse(
            message=response,
            session_id=request.session_id or "new_session"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze")
async def analyze_content(request: dict):
    try:
        content = request.get("content", "")
        instruction = request.get("instruction", "请分析以下内容")
        
        # MiMo-V2-Flash 支持 256K 上下文
        prompt = f"""{instruction}

内容：
{content[:80000]}

请提供详细的分析结果。"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await llm_service.chat_completion(messages, temperature=0.5)
        
        return {"analysis": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

import logging
import json
from typing import Dict, Any, List, Optional
from uuid import UUID, uuid4
from app.services.llm_service import llm_service
from app.services.document_processor import DocxParser, XlsxParser, MdParser, TxtParser

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(self):
        self.parsers = {
            "docx": DocxParser(),
            "xlsx": XlsxParser(),
            "md": MdParser(),
            "txt": TxtParser()
        }
    
    async def analyze_intent(
        self,
        user_message: str,
        documents_info: List[Dict[str, Any]],
        template_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """分析用户意图"""
        
        docs_desc = ""
        if documents_info:
            docs_desc = "用户已选择以下文档：\n"
            for idx, doc in enumerate(documents_info, 1):
                docs_desc += f"{idx}. {doc.get('filename', '未知')} ({doc.get('file_type', '')})\n"
        
        template_desc = ""
        if template_info:
            template_desc = f"用户已选择模板：{template_info.get('filename', '未知')} ({template_info.get('file_type', '')})\n"
        
        prompt = f"""你是一个文档处理智能助手。请分析用户的意图，判断用户想要执行什么操作。

{docs_desc}
{template_desc}

用户消息：{user_message}

请判断用户的意图，返回JSON格式：
```json
{{
    "intent": "意图类型",
    "confidence": 0.0-1.0,
    "action": "需要执行的操作",
    "params": {{
        "instruction": "具体指令"
    }},
    "need_confirm": true/false,
    "confirm_message": "需要确认时的提示信息"
}}
```

意图类型包括：
1. "chat" - 普通对话，如问候、询问功能等
2. "fill_table" - 表格填写，用户想用数据填写模板
3. "query_content" - 内容查询，用户想了解文档内容
4. "operation" - 文档操作，如格式转换、编辑等

判断规则：
- 如果用户说"填写"、"填入"、"填充"等词，或提到模板，判定为fill_table
- 如果用户问"什么内容"、"讲了什么"、"总结"等，判定为query_content
- 如果用户问"你能做什么"、"帮助"等，判定为chat
- fill_table需要确认
- 如果用户没有选择模板但要求填写，need_confirm为true并在confirm_message中提示

只返回JSON，不要其他说明。"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await llm_service.chat_completion(messages, temperature=0.3, max_tokens=1000)
        
        try:
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].strip()
            return json.loads(json_str)
        except Exception as e:
            logger.error("Intent analysis error: %s", e)
            return {
                "intent": "chat",
                "confidence": 0.5,
                "action": "chat",
                "params": {},
                "need_confirm": False,
                "confirm_message": ""
            }
    
    async def summarize_documents(
        self,
        documents_content: List[Dict[str, Any]],
        template_content: Optional[Dict[str, Any]] = None
    ) -> str:
        """总结文档和模板内容，超长文本分块汇总"""

        # 单个内容的最大长度（token预算），留出空间给prompt和输出
        CHUNK_SIZE = 200000

        async def summarize_single(name: str, content: str) -> str:
            """总结单个文档/模板，超长时分块再汇总"""
            if len(content) <= CHUNK_SIZE:
                prompt = f"请用2-3句话简洁地总结以下{name}的核心内容：\n\n{content}"
                return await llm_service.chat_completion(
                    [{"role": "user", "content": prompt}],
                    temperature=0.5, max_tokens=1000
                )

            # 分块
            chunks = []
            for i in range(0, len(content), CHUNK_SIZE):
                chunks.append(content[i:i + CHUNK_SIZE])

            # 逐块总结
            chunk_summaries = []
            for idx, chunk in enumerate(chunks, 1):
                prompt = f"这是{name}的第{idx}/{len(chunks)}部分，请用1-2句话总结这部分内容：\n\n{chunk}"
                summary = await llm_service.chat_completion(
                    [{"role": "user", "content": prompt}],
                    temperature=0.5, max_tokens=500
                )
                chunk_summaries.append(summary)

            # 汇总各块总结
            merged = "\n".join(chunk_summaries)
            prompt = f"以下是{name}各部分的总结，请合并为一段2-3句话的整体总结：\n\n{merged}"
            return await llm_service.chat_completion(
                [{"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=1000
            )

        results = []

        # 逐个总结文档
        for idx, doc in enumerate(documents_content, 1):
            name = f"文档{idx}：{doc['filename']}"
            summary = await summarize_single(name, doc["content"])
            results.append(f"- {name}：{summary}")

        # 总结模板
        if template_content:
            name = f"模板：{template_content['filename']}"
            summary = await summarize_single(name, template_content["content"])
            results.append(f"- {name}：{summary}")

        return "\n\n".join(results)
    
    async def chat_response(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        documents_content: Optional[List[Dict[str, Any]]] = None,
        template_content: Optional[Dict[str, Any]] = None
    ) -> str:
        """普通对话回复"""
        
        context = ""
        if documents_content:
            context = "\n用户当前选择的文档：\n"
            for idx, doc in enumerate(documents_content, 1):
                context += f"{idx}. {doc['filename']} ({doc['file_type']})\n"
        
        if template_content:
            context += f"\n用户当前选择的模板：\n- {template_content['filename']} ({template_content['file_type']})\n"
            context += f"  模板内容预览：{template_content.get('content', '')[:500]}...\n"
        
        system_prompt = f"""你是DocFusion智能文档助手。你可以帮助用户：
1. 读取和理解文档内容
2. 提取文档中的关键信息
3. 根据模板填写表格
4. 回答关于文档的问题

{context}

请用简洁友样的方式回复用户。如果用户问到文档或模板，请提及它们的名称。"""
        
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history[-10:])  # 最近10条对话
        messages.append({"role": "user", "content": user_message})
        
        return await llm_service.chat_completion(messages, temperature=0.7, max_tokens=2000)


agent_service = AgentService()

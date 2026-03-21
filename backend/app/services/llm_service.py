import json
import httpx
from typing import List, Dict, Any, Optional
from app.core.config import get_settings

settings = get_settings()


class LLMService:
    def __init__(self):
        self.api_key = settings.MIMO_API_KEY
        self.base_url = settings.MIMO_BASE_URL
        self.model = settings.MIMO_MODEL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
    
    async def extract_entities(self, text: str, entity_types: List[str] = None) -> List[Dict[str, Any]]:
        prompt = f"""请从以下文本中提取实体信息。返回JSON格式的实体列表。

文本内容：
{text[:8000]}

请提取以下类型的实体（如未指定则提取所有）：
- 人名 (PERSON)
- 地名 (LOCATION) 
- 机构名 (ORGANIZATION)
- 日期 (DATE)
- 数值 (NUMBER)
- 其他关键实体

返回格式：
```json
[
    {{
        "entity_type": "实体类型",
        "entity_name": "实体名称",
        "entity_value": "实体值或上下文",
        "context": "出现的句子"
    }}
]
```

只返回JSON，不要其他说明。"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3)
        
        try:
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].strip()
            return json.loads(json_str)
        except:
            return []
    
    async def extract_table_data(
        self,
        source_text: str,
        template_structure: Dict[str, Any],
        user_instruction: str
    ) -> Dict[str, Any]:
        prompt = f"""根据以下源文档内容和模板结构，提取并填写表格数据。

用户指令：
{user_instruction}

模板结构：
{json.dumps(template_structure, ensure_ascii=False, indent=2)}

源文档内容（部分）：
{source_text[:6000]}

请根据模板结构从源文档中提取对应数据，返回JSON格式的填写结果。
返回格式为一个字典，key为sheet名称，value为包含columns和data的对象。

只返回JSON数据，不要其他说明。"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3)
        
        try:
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].strip()
            return json.loads(json_str)
        except Exception as e:
            return {"error": str(e), "raw_response": response}
    
    async def document_operation(
        self,
        document_content: str,
        instruction: str,
        document_type: str
    ) -> Dict[str, Any]:
        prompt = f"""你是一个文档智能助手。根据用户的自然语言指令，对文档内容进行操作。

文档类型：{document_type}

文档内容（部分）：
{document_content[:6000]}

用户指令：
{instruction}

请执行用户的指令并返回结果。返回格式：
```json
{{
    "operation_type": "操作类型（extract/edit/format/convert/query）",
    "result": "操作结果或提取的内容",
    "success": true/false,
    "message": "操作说明"
}}
```

只返回JSON，不要其他说明。"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3)
        
        try:
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].strip()
            return json.loads(json_str)
        except:
            return {"operation_type": "query", "result": response, "success": True, "message": "已处理"}
    
    async def analyze_relationships(self, entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        prompt = f"""分析以下实体之间的关系，返回关系列表。

实体列表：
{json.dumps(entities[:50], ensure_ascii=False, indent=2)}

请分析这些实体之间的关系，返回JSON格式的关系列表。

返回格式：
```json
[
    {{
        "source": "源实体名称",
        "target": "目标实体名称",
        "relation_type": "关系类型",
        "description": "关系描述"
    }}
]
```

只返回JSON，不要其他说明。"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3)
        
        try:
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].strip()
            return json.loads(json_str)
        except:
            return []


llm_service = LLMService()

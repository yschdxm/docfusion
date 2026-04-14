import json
import logging
from typing import Any, Dict, List

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMService:
    def __init__(self):
        self.api_key = settings.MIMO_API_KEY
        self.base_url = settings.MIMO_BASE_URL.strip().rstrip("/")
        self.model = settings.MIMO_MODEL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _is_deepseek(self) -> bool:
        base_url = self.base_url.lower()
        model = self.model.lower()
        return "deepseek" in base_url or model.startswith("deepseek")

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        payload["max_tokens"] = min(max_tokens, 4096) if self._is_deepseek() else max_tokens
        return payload

    def _parse_json_response(self, response: str, fallback: Any) -> Any:
        try:
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```", 1)[1].strip()
            return json.loads(json_str)
        except Exception as exc:
            logger.error("Failed to parse JSON response: error=%s response=%s", exc, response[:500])
            return fallback

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 65536,
    ) -> str:
        async with httpx.AsyncClient(timeout=600.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=self._build_payload(messages, temperature, max_tokens),
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                logger.error(
                    "LLM request failed: model=%s url=%s status=%s body=%s",
                    self.model,
                    response.request.url,
                    response.status_code,
                    response.text[:1000],
                )
                raise
            result = response.json()
            return result["choices"][0]["message"]["content"]

    async def extract_entities(self, text: str, entity_types: List[str] = None) -> List[Dict[str, Any]]:
        prompt = f"""请从下面文本中提取实体，并仅返回 JSON 数组。

文本:
{text[:80000]}

实体类型优先包括 PERSON、LOCATION、ORGANIZATION、DATE、NUMBER。

返回格式:
```json
[
  {{
    \"entity_type\": \"PERSON\",
    \"entity_name\": \"张三\",
    \"entity_value\": \"张三\",
    \"context\": \"张三负责项目验收\"
  }}
]
```
"""
        response = await self.chat_completion([{"role": "user", "content": prompt}], temperature=0.3)
        return self._parse_json_response(response, [])

    async def extract_table_data(
        self,
        source_text: str,
        template_structure: Dict[str, Any],
        user_instruction: str,
    ) -> Dict[str, Any]:
        prompt = f"""请根据源文档内容和模板结构提取表格填写数据，只返回 JSON。

用户指令:
{user_instruction}

模板结构:
{json.dumps(template_structure, ensure_ascii=False, indent=2)}

源文档内容:
{source_text[:80000]}
"""
        response = await self.chat_completion([{"role": "user", "content": prompt}], temperature=0.3)
        parsed = self._parse_json_response(response, None)
        if parsed is None:
            return {"error": "JSON parse failed", "raw_response": response}
        return parsed

    async def plan_document_operations(
        self,
        document_structure: Dict[str, Any],
        instruction: str,
        document_type: str,
    ) -> Dict[str, Any]:
        prompt = f"""你是文档操作规划器。你的职责是根据用户指令，输出可执行的固定 JSON 操作计划，不能直接返回改好的全文。

文档类型: {document_type}
用户指令: {instruction}

文档结构:
{json.dumps(document_structure, ensure_ascii=False, indent=2)}

你只能使用以下操作:
- replace_text
- rewrite_paragraph
- insert_after
- heading_promote
- list_format
- paragraph_split
- convert

操作约束:
- replace_text: target.paragraph_index + params.old_text + params.new_text
- rewrite_paragraph: target.paragraph_index + params.rewrite_instruction
- insert_after: target.paragraph_index + params.text，可选 params.style
- heading_promote: target.paragraph_index + params.level(1-6)
- list_format: target.paragraph_indexes + params.list_type(bullet/number)
- paragraph_split: target.paragraph_index，可选 params.separator
- convert: params.target_format

格式转换限制:
- docx -> md / txt
- md -> docx / txt
- txt -> md / docx
- xlsx -> csv

规划原则:
- 只引用已有段落索引
- 优先最小改动
- 如果无法完成，operations 返回空数组，并在 message 说明原因
- 只输出 JSON，不要输出解释

返回格式:
```json
{{
  \"intent\": \"document_operation\",
  \"document_type\": \"{document_type}\",
  \"summary\": \"一句话概括计划\",
  \"need_confirm\": false,
  \"response_mode\": \"preview\",
  \"message\": \"简短说明\",
  \"operations\": [
    {{
      \"op\": \"replace_text\",
      \"target\": {{
        \"paragraph_index\": 0,
        \"paragraph_indexes\": [0, 1]
      }},
      \"params\": {{
        \"old_text\": \"旧文本\",
        \"new_text\": \"新文本\",
        \"rewrite_instruction\": \"改写要求\",
        \"text\": \"插入文本\",
        \"style\": \"Normal\",
        \"level\": 1,
        \"list_type\": \"bullet\",
        \"separator\": \"；\",
        \"target_format\": \"md\"
      }},
      \"reason\": \"原因\"
    }}
  ]
}}
```
"""
        response = await self.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=4000,
        )
        return self._parse_json_response(
            response,
            {
                "intent": "document_operation",
                "document_type": document_type,
                "summary": "未能生成有效操作计划",
                "need_confirm": False,
                "response_mode": "preview",
                "message": "未能生成有效操作计划",
                "operations": [],
            },
        )

    async def rewrite_paragraph_text(self, text: str, instruction: str) -> str:
        prompt = f"""你是文档段落改写助手。

请只改写下面这一段内容，不要添加解释，不要返回多段。

改写要求:
{instruction}

原始段落:
{text}
"""
        response = await self.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=2000,
        )
        return response.strip()

    async def document_operation(
        self,
        document_content: str,
        instruction: str,
        document_type: str,
    ) -> Dict[str, Any]:
        document_structure = {
            "file_type": document_type,
            "paragraphs": [
                {"index": idx, "text": paragraph}
                for idx, paragraph in enumerate([item for item in document_content.split("\n") if item.strip()])
            ],
        }
        return await self.plan_document_operations(document_structure, instruction, document_type)

    async def analyze_relationships(self, entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        prompt = f"""请分析以下实体之间的关系，只返回 JSON 数组。

实体列表:
{json.dumps(entities[:200], ensure_ascii=False, indent=2)}

返回格式:
```json
[
  {{
    \"source\": \"实体A\",
    \"target\": \"实体B\",
    \"relation_type\": \"关系类型\",
    \"description\": \"关系描述\"
  }}
]
```
"""
        response = await self.chat_completion([{"role": "user", "content": prompt}], temperature=0.3)
        return self._parse_json_response(response, [])


llm_service = LLMService()

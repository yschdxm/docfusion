import json
import httpx
import logging
import re
from typing import List, Dict, Any
from app.core.config import get_settings
from app.services.prompts import (
    NER_PROMPT,
    QUERY_GENERATION_PROMPT,
    ANSWER_EXTRACTION_PROMPT,
    SQL_GENERATION_PROMPT,
    ROW_FILL_PROMPT,
    BATCH_EXTRACT_PROMPT,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMService:
    def __init__(self):
        self.api_key = settings.MIMO_API_KEY
        self.base_url = settings.MIMO_BASE_URL
        self.model = settings.MIMO_MODEL
        self.ssl_verify = settings.SSL_VERIFY and settings.SSL_VERIFY_MIMO
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        logger.info(f"LLMService初始化: model={self.model}, base_url={self.base_url}, ssl_verify={self.ssl_verify}")

    @staticmethod
    def _extract_json(text: str) -> Any:
        """从 LLM 响应中鲁棒地提取 JSON。"""
        text = text.strip()

        # 1. ```json ... ``` 包裹
        json_block = re.search(r'```json\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
        if json_block:
            return json.loads(json_block.group(1).strip())

        # 2. ``` ... ``` 包裹（无 json 标签）
        code_block = re.search(r'```\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
        if code_block:
            return json.loads(code_block.group(1).strip())

        # 3. 平衡花括号匹配
        brace_start = text.find('{')
        if brace_start >= 0:
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[brace_start:i + 1])

        # 4. 平衡方括号匹配
        bracket_start = text.find('[')
        if bracket_start >= 0:
            depth = 0
            for i in range(bracket_start, len(text)):
                if text[i] == '[':
                    depth += 1
                elif text[i] == ']':
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[bracket_start:i + 1])

        # 5. 直接解析
        return json.loads(text)

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 65536
    ) -> str:
        async with httpx.AsyncClient(timeout=600.0, verify=self.ssl_verify) as client:
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

    # ──────────────────────────── 实体关系提取 ────────────────────────────

    async def extract_entities_and_relations(
        self,
        text: str,
    ) -> Dict[str, Any]:
        """使用 100+ 实体类型 NER 提示词提取实体和关系。

        Returns:
            {"entities": [...], "relations": [...]}
        """
        prompt = NER_PROMPT.format(text=text[:80000])

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3)

        try:
            result = self._extract_json(response)
            if isinstance(result, dict):
                return result
            return {"entities": result if isinstance(result, list) else [], "relations": []}
        except json.JSONDecodeError as e:
            logger.error(f"NER JSON解析失败: response={response[:200]}, error={e}")
            return {"entities": [], "relations": []}
        except Exception as e:
            logger.error(f"NER异常: error={e}")
            return {"entities": [], "relations": []}

    # ──────────────────────────── 表格填写相关 ────────────────────────────

    async def generate_search_queries(
        self,
        field_name: str,
        row_context: str = "",
        table_headers: str = "",
    ) -> List[str]:
        """从字段名+行上下文生成搜索查询。

        Returns:
            ["query1", "query2", "query3"]
        """
        prompt = QUERY_GENERATION_PROMPT.format(
            field_name=field_name,
            row_context=row_context,
            table_headers=table_headers,
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=1000)

        try:
            result = self._extract_json(response)
            return result.get("queries", [field_name])
        except Exception:
            return [field_name]

    async def extract_answer_from_context(
        self,
        query: str,
        field_name: str,
        contexts: List[str],
    ) -> Dict[str, Any]:
        """从检索到的上下文中提取答案。

        Returns:
            {"answer": str|None, "confidence": float, "source": str}
        """
        context_text = "\n---\n".join(contexts[:5])
        prompt = ANSWER_EXTRACTION_PROMPT.format(
            query=query,
            field_name=field_name,
            context_text=context_text,
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=2000)

        try:
            return self._extract_json(response)
        except Exception:
            return {"answer": None, "confidence": 0.0, "source": "解析失败"}

    async def generate_sql(self, schema_info: str, question: str) -> Dict[str, Any]:
        """根据表结构信息生成 SQL 查询。

        Returns:
            {"sql": str, "explanation": str}
        """
        prompt = SQL_GENERATION_PROMPT.format(
            schema_info=schema_info,
            query=question,
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=2000)

        try:
            return self._extract_json(response)
        except Exception:
            return {"sql": "", "explanation": "SQL 生成失败"}

    async def extract_row_answers(
        self,
        table_headers: str,
        row_context: str,
        empty_fields: str,
        contexts: List[str],
    ) -> Dict[str, Any]:
        """行级批量提取：一次 LLM 调用填写一行中所有空字段。

        Returns:
            {"answers": {"字段名": "值"|null, ...}, "confidence": float}
        """
        context_text = "\n---\n".join(contexts[:5])
        prompt = ROW_FILL_PROMPT.format(
            table_headers=table_headers,
            row_context=row_context,
            empty_fields=empty_fields,
            context_text=context_text,
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=2000)

        try:
            return self._extract_json(response)
        except Exception:
            return {"answers": {}, "confidence": 0.0}

    async def batch_extract_records(
        self,
        table_headers: str,
        contexts: List[str],
        table_context: str = "",
    ) -> List[Dict[str, str]]:
        """从源文档中批量提取所有符合表头结构的记录。

        Returns:
            [{"字段名1": "值1", "字段名2": "值2", ...}, ...]
        """
        context_text = "\n---\n".join(contexts[:5])
        prompt = BATCH_EXTRACT_PROMPT.format(
            table_headers=table_headers,
            context_text=context_text,
            table_context=table_context or "无",
        )

        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.3, max_tokens=16000)
        logger.debug("[BATCH-EXTRACT] LLM响应长度: %d", len(response) if response else 0)

        try:
            result = self._extract_json(response)
            records = result.get("records", [])
            logger.debug("[BATCH-EXTRACT] 解析成功: %d 条记录", len(records))
            return records
        except Exception as e:
            logger.warning("[BATCH-EXTRACT] JSON解析失败: %s, response前200字: %s", e, response[:200] if response else "None")
            return []

    async def map_columns(
        self,
        template_headers: List[str],
        db_columns: List[str],
    ) -> Dict[str, str]:
        """用 AI 建立模板表头到数据库列名的映射。

        Returns:
            {"模板表头": "数据库列名", ...}
        """
        prompt = f"""请建立模板表头和数据库列名之间的映射关系。

模板表头：{template_headers}
数据库列名：{db_columns}

要求：
1. 每个模板表头对应一个数据库列名
2. 如果名称有差异但含义相同（如 PM2.5监测值 和 PM2_5监测值），建立映射
3. 如果找不到对应关系，不返回该表头

输出格式（JSON）：
{{"模板表头1": "数据库列名1", "模板表头2": "数据库列名2"}}

只返回JSON，不要其他说明。"""
        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, temperature=0.1, max_tokens=1000)
        try:
            return self._extract_json(response)
        except Exception:
            return {}

    # ──────────────────────────── 文档操作 ────────────────────────────

    async def document_operation(
        self,
        document_content: str,
        instruction: str,
        document_type: str
    ) -> Dict[str, Any]:
        prompt = f"""你是一个文档智能助手。根据用户的自然语言指令，对文档内容进行操作。

文档类型：{document_type}

文档内容：
{document_content[:80000]}

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
            return self._extract_json(response)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: response={response[:200]}, error={e}")
            return {"operation_type": "query", "result": response, "success": False, "message": "响应解析失败"}
        except Exception as e:
            logger.error(f"响应处理异常: error={e}")
            return {"operation_type": "query", "result": response, "success": False, "message": "响应处理异常"}


llm_service = LLMService()

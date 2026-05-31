"""
文档提取工具 - 从多个文档中提取指定字段的信息

功能：
- 从多个文档中批量提取信息
- 使用RAG检索 + LLM提取结构化记录
- 返回统一的提取结果
"""

import logging
from typing import Any, Dict, List

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.services.rag_service import rag_service
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)


class ExtractFromDocsTool(BaseTool):
    """文档提取工具

    从多个文档中提取指定字段的信息，支持多种提取策略。
    这是数据查找的最后手段（PG > Neo4j > RAG > 原文档）。
    """

    @property
    def name(self) -> str:
        return "extract_from_documents"

    @property
    def description(self) -> str:
        return """从多个文档中提取指定字段的信息。内部使用向量检索找到相关片段，再用LLM批量提取结构化记录。

使用场景：
- 需要从非结构化文档（docx/md/txt）中提取表格数据
- PG和Neo4j查询未找到数据时的补充手段
- 批量提取多个字段

数据查找优先级：
1. PostgreSQL - xlsx结构化数据首选
2. Neo4j知识图谱 - 实体关系数据
3. 此工具（RAG检索+LLM提取） - 非结构化文档的首选手段"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "doc_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要提取的文档ID列表"
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要提取的字段列表，例如：[\"城市\", \"GDP\", \"人口\"]"
                },
                "extraction_mode": {
                    "type": "string",
                    "enum": ["rag", "hybrid"],
                    "default": "hybrid",
                    "description": "提取模式: rag(向量检索)、hybrid(混合)"
                },
                "max_records": {
                    "type": "integer",
                    "default": 50,
                    "description": "最大返回记录数"
                }
            },
            "required": ["doc_ids", "fields"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行文档提取"""
        try:
            doc_ids = params.get("doc_ids", [])
            fields = params.get("fields", [])
            extraction_mode = params.get("extraction_mode", "hybrid")
            max_records = params.get("max_records", 50)

            if not doc_ids:
                return ToolResult(
                    success=False,
                    error="文档ID列表不能为空"
                )

            if not fields:
                return ToolResult(
                    success=False,
                    error="字段列表不能为空"
                )

            all_records = []
            errors = []

            # 使用RAG检索 + LLM提取
            for doc_id in doc_ids:
                try:
                    records = await self._extract_with_rag(doc_id, fields, max_records)
                    all_records.extend(records)
                except Exception as e:
                    error_msg = f"文档 {doc_id} 提取失败: {str(e)}"
                    logger.error(f"[ExtractFromDocsTool] {error_msg}")
                    errors.append(error_msg)

            # 去重（使用所有字段组合作为去重 key，避免仅按首字段误删）
            seen = set()
            unique_records = []
            for record in all_records:
                key = "|".join(
                    f"{k}={v}" for k, v in sorted(record.items())
                    if v is not None and str(v).strip()
                )
                if key and key not in seen:
                    seen.add(key)
                    unique_records.append(record)

            # 限制记录数
            unique_records = unique_records[:max_records]

            # 如果所有文档都失败了且没有任何记录，返回错误
            if not unique_records and errors and len(errors) == len(doc_ids):
                return ToolResult(
                    success=False,
                    error="所有文档提取均失败:\n" + "\n".join(errors),
                )

            return ToolResult(
                success=True,
                data={
                    "fields": fields,
                    "records_count": len(unique_records),
                    "records": unique_records,
                    "extraction_mode": extraction_mode,
                },
                metadata={
                    "doc_ids": doc_ids,
                    "queried_doc_count": len(doc_ids),
                    "errors": errors if errors else None,
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"文档提取失败: {str(e)}"
            )

    async def _extract_with_rag(self, doc_id: str, fields: List[str], max_records: int = 50) -> List[Dict]:
        """使用RAG检索并提取信息"""
        records = []

        try:
            # 根据max_records动态调整top_k，确保检索足够的数据
            top_k = min(max(10, max_records // 5), 30)

            # 为所有字段生成一个综合查询
            fields_str = "、".join(fields)
            query = f"提取以下字段的所有信息：{fields_str}"

            results = await rag_service.search_for_field(
                query=query,
                doc_ids=[doc_id],
                top_k=top_k
            )

            # 合并检索结果
            contexts = [r.get("content", "") for r in results]

            if contexts:
                # 使用LLM批量提取记录
                table_headers = "，".join(fields)
                extracted_records = await llm_service.batch_extract_records(
                    table_headers=table_headers,
                    contexts=contexts,
                    table_context="从文档中提取指定字段的数据",
                    document_title=f"文档 {doc_id}",
                    max_records=max_records
                )
                records.extend(extracted_records)

        except Exception as e:
            print(f"RAG提取失败 {doc_id}: {e}")

        return records

"""
文档提取工具 - 从多个文档中提取指定字段的信息

功能：
- 从多个文档中批量提取信息
- 支持结构化、RAG、混合三种模式
- 返回统一的提取结果
"""

from typing import Any, Dict, List

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.services.rag_service import rag_service
from app.services.llm_service import llm_service


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
        return """从多个文档中提取指定字段的信息。

使用场景：
- PG和Neo4j查询未找到完整数据时
- 需要从原始文档中提取特定信息
- 批量提取多个字段

提取模式：
- structured: 使用结构化方法提取（基于文档结构）
- rag: 使用RAG检索后提取
- hybrid: 混合模式（先RAG，再结构化）

数据查找优先级：
1. PostgreSQL - 结构化数据
2. Neo4j知识图谱 - 实体关系数据
3. RAG向量检索 - 非结构化文本
4. 原始文档提取 (此工具) - 最后手段"""

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
                    "enum": ["structured", "rag", "hybrid"],
                    "default": "hybrid",
                    "description": "提取模式: structured(结构化)、rag(向量检索)、hybrid(混合)"
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

            # 根据提取模式选择策略
            if extraction_mode in ["rag", "hybrid"]:
                # 使用RAG检索
                for doc_id in doc_ids:
                    try:
                        records = await self._extract_with_rag(doc_id, fields)
                        all_records.extend(records)
                    except Exception as e:
                        print(f"RAG提取失败 {doc_id}: {e}")

            # 如果hybrid模式且RAG结果不足，可以尝试其他方法
            # 这里简化处理，仅使用RAG

            # 去重
            seen = set()
            unique_records = []
            for record in all_records:
                # 使用第一个字段作为去重键
                key = str(record.get(fields[0], "")) if fields else str(record)
                if key and key not in seen:
                    seen.add(key)
                    unique_records.append(record)

            # 限制记录数
            unique_records = unique_records[:max_records]

            return ToolResult(
                success=True,
                data={
                    "fields": fields,
                    "records_count": len(unique_records),
                    "records": unique_records,
                    "extraction_mode": extraction_mode
                },
                metadata={
                    "doc_ids": doc_ids,
                    "queried_doc_count": len(doc_ids)
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"文档提取失败: {str(e)}"
            )

    async def _extract_with_rag(self, doc_id: str, fields: List[str]) -> List[Dict]:
        """使用RAG检索并提取信息"""
        records = []

        try:
            # 为所有字段生成一个综合查询
            fields_str = "、".join(fields)
            query = f"提取以下字段的所有信息：{fields_str}"

            results = await rag_service.search_relevant_documents(
                query=query,
                doc_ids=[doc_id],
                top_k=10
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
                    document_title=f"文档 {doc_id}"
                )
                records.extend(extracted_records)

        except Exception as e:
            print(f"RAG提取失败 {doc_id}: {e}")

        return records

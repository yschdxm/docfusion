"""
知识图谱工具 - 知识图谱的构建、查询和分析

功能：
- 从文档中提取实体和关系，构建知识图谱
- 查找与指定实体相关的所有实体
- 获取指定实体的详细信息
"""

import logging
from typing import Any, Dict, List

from app.agent.base.tool import BaseTool, ToolContext, ToolResult, ToolCategory, PermissionLevel
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select

logger = logging.getLogger(__name__)


class BuildKnowledgeGraphTool(BaseTool):
    """构建知识图谱工具"""

    @property
    def name(self) -> str:
        return "build_knowledge_graph"

    @property
    def description(self) -> str:
        return """从文档中提取实体和关系，构建知识图谱。

使用场景：
- 当需要从文档中自动提取人名、地名、机构等实体时
- 当需要分析文档中的实体关系时
- 当需要构建文档的知识图谱时

注意事项：
- 此操作可能需要较长时间（最多5分钟）
- 提取质量取决于文档内容的质量和结构
- 建议先对少量文档测试，确认效果后再批量处理"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.KNOWLEDGE

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SENSITIVE

    @property
    def timeout_ms(self) -> int:
        return 300000  # 5分钟

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "文档ID列表"
                },
                "entity_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要提取的实体类型（可选，默认提取所有类型）"
                },
                "relation_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要提取的关系类型（可选，默认提取所有类型）"
                }
            },
            "required": ["file_ids"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """构建知识图谱"""
        try:
            file_ids = params.get("file_ids", [])
            entity_types = params.get("entity_types", [])
            relation_types = params.get("relation_types", [])

            if not file_ids:
                return ToolResult(success=False, error="文档ID列表不能为空")

            # 查询文档信息
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id.in_(file_ids))
                )
                docs = result.scalars().all()

                if not docs:
                    return ToolResult(success=False, error="未找到指定的文档")

                # 调用知识图谱服务构建图谱
                from app.services.knowledge_graph_service import knowledge_graph_service

                total_entities = 0
                total_relations = 0
                processed_docs = []

                for doc in docs:
                    try:
                        # 提取实体和关系
                        extraction_result = await knowledge_graph_service.extract_from_document(
                            doc_id=str(doc.id),
                            file_path=doc.file_path,
                            file_type=doc.file_type,
                            entity_types=entity_types if entity_types else None,
                            relation_types=relation_types if relation_types else None
                        )

                        # 写入Neo4j
                        await knowledge_graph_service.build_graph_from_entities(
                            entities=extraction_result.get("entities", []),
                            relations=extraction_result.get("relations", []),
                            document_id=str(doc.id)
                        )

                        total_entities += len(extraction_result.get("entities", []))
                        total_relations += len(extraction_result.get("relations", []))
                        processed_docs.append({
                            "doc_id": str(doc.id),
                            "filename": doc.original_filename,
                            "entities_count": len(extraction_result.get("entities", [])),
                            "relations_count": len(extraction_result.get("relations", []))
                        })

                    except Exception as e:
                        logger.error(f"处理文档 {doc.id} 失败: {e}")
                        processed_docs.append({
                            "doc_id": str(doc.id),
                            "filename": doc.original_filename,
                            "error": str(e)
                        })

                return ToolResult(
                    success=True,
                    data={
                        "message": f"知识图谱构建完成",
                        "processed_documents": len(processed_docs),
                        "total_entities": total_entities,
                        "total_relations": total_relations,
                        "details": processed_docs
                    }
                )

        except Exception as e:
            logger.exception(f"构建知识图谱失败: {e}")
            return ToolResult(success=False, error=f"构建知识图谱失败: {str(e)}")


class FindRelatedEntitiesTool(BaseTool):
    """查找关联实体工具"""

    @property
    def name(self) -> str:
        return "find_related_entities"

    @property
    def description(self) -> str:
        return """查找与指定实体相关的所有实体。

使用场景：
- 当需要了解某个实体与其他实体的关系时
- 当需要查找某个实体的关联信息时
- 当需要分析实体之间的关系网络时

注意事项：
- depth参数控制关系深度，较大的值可能返回大量结果
- 可以通过relation_types过滤特定类型的关系"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.KNOWLEDGE

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 15000  # 15秒

    @property
    def cacheable(self) -> bool:
        return True

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "实体名称"
                },
                "depth": {
                    "type": "integer",
                    "default": 2,
                    "description": "关系深度（默认2）"
                },
                "relation_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "关系类型过滤（可选）"
                }
            },
            "required": ["entity_name"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """查找关联实体"""
        try:
            entity_name = params.get("entity_name", "")
            depth = params.get("depth", 2)
            relation_types = params.get("relation_types", [])

            if not entity_name:
                return ToolResult(success=False, error="实体名称不能为空")

            # 调用知识图谱服务查询关联实体
            from app.services.knowledge_graph_service import knowledge_graph_service

            related_entities = await knowledge_graph_service.find_related_entities(
                entity_name=entity_name,
                depth=depth,
                relation_types=relation_types if relation_types else None
            )

            return ToolResult(
                success=True,
                data={
                    "entity_name": entity_name,
                    "depth": depth,
                    "related_entities": related_entities,
                    "total_count": len(related_entities)
                }
            )

        except Exception as e:
            logger.exception(f"查找关联实体失败: {e}")
            return ToolResult(success=False, error=f"查找关联实体失败: {str(e)}")


class GetEntityDetailsTool(BaseTool):
    """获取实体详情工具"""

    @property
    def name(self) -> str:
        return "get_entity_details"

    @property
    def description(self) -> str:
        return """获取指定实体的详细信息。

使用场景：
- 当需要了解某个实体的详细属性时
- 当需要查看某个实体的来源文档时
- 当需要获取某个实体的关系列表时

注意事项：
- include_relations参数控制是否返回关系信息
- 如果实体不存在，将返回错误"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.KNOWLEDGE

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 10000  # 10秒

    @property
    def cacheable(self) -> bool:
        return True

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "实体名称"
                },
                "include_relations": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否包含关系信息"
                }
            },
            "required": ["entity_name"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """获取实体详情"""
        try:
            entity_name = params.get("entity_name", "")
            include_relations = params.get("include_relations", True)

            if not entity_name:
                return ToolResult(success=False, error="实体名称不能为空")

            # 调用知识图谱服务查询实体详情
            from app.services.knowledge_graph_service import knowledge_graph_service

            entity_details = await knowledge_graph_service.get_entity_details(
                entity_name=entity_name,
                include_relations=include_relations
            )

            if not entity_details:
                return ToolResult(success=False, error=f"实体不存在: {entity_name}")

            return ToolResult(
                success=True,
                data=entity_details
            )

        except Exception as e:
            logger.exception(f"获取实体详情失败: {e}")
            return ToolResult(success=False, error=f"获取实体详情失败: {str(e)}")

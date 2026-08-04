"""
文档列表工具 - 列出所有可用文档

功能：
- 列出所有源文档
- 列出所有模板文档
- 返回文档基本信息
"""

from typing import Any, Dict
from uuid import UUID

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select, func, and_, or_


class ListDocumentsTool(BaseTool):
    """文档列表工具

    列出系统中所有可用的文档，包括源文档和模板文档。
    Agent可以通过此工具了解可用资源。
    """

    @property
    def name(self) -> str:
        return "list_documents"

    @property
    def description(self) -> str:
        return """列出所有可用的源文档和模板文档。

使用场景：
- 任务开始时了解有哪些文档可用
- 需要确认文档ID时
- 查看文档类型和状态

返回信息：
- 文档ID
- 文件名
- 文件类型
- 文档分类(source/template)
- 处理状态"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["source", "template", "all"],
                    "default": "all",
                    "description": "文档分类过滤: source(源文档)、template(模板)、all(全部)"
                }
            }
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行文档列表查询"""
        try:
            category = params.get("category", "all")

            async with async_session() as db:
                # 只列出每个逻辑文档（root）的最新版本，避免 LLM 看到全部历史版本
                root_expr = func.coalesce(Document.root_document_id, Document.id)
                latest_subq = (
                    select(
                        root_expr.label("root_id"),
                        func.max(Document.version).label("max_version"),
                    )
                    .group_by(root_expr)
                    .subquery()
                )
                query = select(Document).join(
                    latest_subq,
                    and_(
                        root_expr == latest_subq.c.root_id,
                        Document.version == latest_subq.c.max_version,
                    ),
                )

                # 用户过滤：只列出当前用户自己的文档和共享文档
                if context.user_id:
                    try:
                        uid = UUID(str(context.user_id))
                        query = query.where(
                            or_(Document.user_id == uid, Document.is_shared.is_(True))
                        )
                    except ValueError:
                        query = query.where(Document.user_id.is_(None))

                if category == "source":
                    query = query.where(Document.doc_category == "source")
                elif category == "template":
                    query = query.where(Document.doc_category == "template")

                query = query.order_by(Document.created_at.desc())

                result = await db.execute(query)
                docs = result.scalars().all()

                # 格式化文档信息
                doc_list = []
                for doc in docs:
                    doc_info = {
                        "id": str(doc.id),
                        "filename": doc.original_filename,
                        "file_type": doc.file_type,
                        "category": doc.doc_category,
                        "status": doc.status,
                        "file_size": doc.file_size,
                        "created_at": doc.created_at.isoformat() if doc.created_at else None
                    }
                    doc_list.append(doc_info)

                # 分类统计
                source_count = sum(1 for d in doc_list if d["category"] == "source")
                template_count = sum(1 for d in doc_list if d["category"] == "template")

                return ToolResult(
                    success=True,
                    data={
                        "total": len(doc_list),
                        "source_count": source_count,
                        "template_count": template_count,
                        "documents": doc_list
                    },
                    metadata={
                        "category_filter": category
                    }
                )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取文档列表失败: {str(e)}"
            )

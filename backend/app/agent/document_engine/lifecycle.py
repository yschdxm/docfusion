"""
写工具的文件生命周期公共层（从 document_edit_tools 提升）

- get_doc_info: file_id → 磁盘路径等文档信息
- resolve_edit_target: 版本化目标解析（同 run 原地改 / 新 run 创建 version+1 /
  source/template 首次编辑创建新 root 输出 v1）
- finish_edit: 写回后更新版本行的大小/哈希，返回下载信息

所有写工具（fill/edit/convert）统一走这里，不再各自内联文件生命周期。
"""

import os
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select

from app.db.postgres import async_session
from app.models.document import Document
from app.services import document_versioning, file_storage


async def get_doc_info(file_id: str) -> Optional[Dict[str, Any]]:
    """通过数据库查询文档信息，返回 {file_path, file_type, original_filename, doc_id, is_output}"""
    try:
        doc_uuid = UUID(str(file_id))
    except ValueError:
        return None

    async with async_session() as db:
        result = await db.execute(select(Document).where(Document.id == doc_uuid))
        doc = result.scalar_one_or_none()
        if doc and doc.file_path and os.path.exists(doc.file_path):
            return {
                "file_path": doc.file_path,
                "file_type": doc.file_type,
                "original_filename": doc.original_filename or os.path.basename(doc.file_path),
                "doc_id": str(doc.id),
                "is_output": (doc.doc_category == "output"),
            }
    return None


async def resolve_edit_target(doc_info: Dict[str, Any], output_file_id: Optional[str], context,
                              origin_type: str = "edit") -> tuple:
    """解析编辑目标（版本化）

    Returns:
        (target_path, original_filename, target_doc_id, is_new_version)
        编辑直接在 target_path 上进行，目标 Document 行已存在。
    """
    run_id = context.metadata.get("run_id") if context else None
    conversation_id = context.metadata.get("conversation_id") if context else None

    async with async_session() as db:
        doc = None
        if output_file_id:
            try:
                result = await db.execute(select(Document).where(Document.id == UUID(str(output_file_id))))
                doc = result.scalar_one_or_none()
            except ValueError:
                doc = None
        if doc is None:
            result = await db.execute(select(Document).where(Document.id == UUID(doc_info["doc_id"])))
            doc = result.scalar_one_or_none()
        if doc is None:
            return doc_info["file_path"], doc_info["original_filename"], doc_info["doc_id"], False

        if doc.doc_category == "output":
            target, is_new = await document_versioning.resolve_output_target(
                db, doc,
                run_id=run_id,
                origin_type=origin_type,
                conversation_id=conversation_id,
            )
        else:
            target = await document_versioning.create_root_output(
                db,
                user_id=doc.user_id,
                file_type=doc.file_type,
                origin_type=origin_type,
                source_doc=doc,
                run_id=run_id,
                conversation_id=conversation_id,
            )
            is_new = True
        await db.commit()
        return target.file_path, target.original_filename, str(target.id), is_new


async def finish_edit(target_doc_id: str, context) -> Dict[str, str]:
    """编辑完成后更新目标版本行的大小/哈希，返回下载信息"""
    async with async_session() as db:
        result = await db.execute(select(Document).where(Document.id == UUID(str(target_doc_id))))
        doc = result.scalar_one_or_none()
        if not doc:
            return {
                "output_file_id": str(target_doc_id),
                "output_filename": "",
                "download_url": f"/api/v1/documents/{target_doc_id}/download",
            }
        if doc.file_path and os.path.exists(doc.file_path):
            doc.file_size = os.path.getsize(doc.file_path)
            doc.sha256 = file_storage.sha256_file(doc.file_path)
        doc.status = "completed"
        await db.commit()
        return document_versioning.download_info(doc)


async def record_template_usage(
    db,
    *,
    template_id: str,
    template_name: str,
    output_file_id: str,
    context,
    source_file_ids: Optional[list] = None,
) -> None:
    """记录模板使用事件（原 fill_table/fill_form 各自内联的逻辑）"""
    from app.models.document import TemplateUsageEvent

    db.add(TemplateUsageEvent(
        user_id=context.user_id if context else None,
        template_id=template_id,
        template_name=template_name,
        source_file_count=len(context.file_ids) if context and context.file_ids else 0,
        source_file_ids=source_file_ids or [],
        output_file_id=output_file_id,
    ))
    await db.commit()

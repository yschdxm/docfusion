"""文档版本链服务：一个逻辑文档 = 一个 root_document_id，每次变更产生 version+1。

核心规则：
- 上传/导入/从零创建/格式转换 → 新 root（root_document_id = 自身 id，v1）
- 首次填/编辑 source 或 template → 新 root 的输出 v1（来源记在 metadata_info.derived_from）
- 同一 run 内对同一输出的连续修改 → 原地改（resolve_output_target 返回原行）
- 新 run 首次修改已有输出 → 同 root 下创建 version+1
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.services import file_storage

logger = logging.getLogger(__name__)

# origin_type → 输出文件名中的操作标签（统一命名规则用）
_ORIGIN_ACTION_LABELS = {
    "fill": "填写",
    "edit": "编辑",
    "convert": "转换",
}


def build_output_filename(source_name: Optional[str], origin_type: str, file_type: str) -> str:
    """统一的输出文件命名：{源文件词干}_{操作}_{YYYYmmdd_HHmm}.{ext}

    例：百强城市模板_填写_20260817_2105.xlsx
    后续版本继承 v1 文件名（create_next_version 不变），由版本号区分。
    """
    stem = os.path.splitext(source_name)[0] if source_name else "document"
    action = _ORIGIN_ACTION_LABELS.get(origin_type, origin_type or "输出")
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    ext = (file_type or "").lstrip(".")
    return f"{stem}_{action}_{ts}.{ext}" if ext else f"{stem}_{action}_{ts}"


MAX_VERSION_RETRIES = 3


async def latest_of_root(db: AsyncSession, root_document_id: uuid.UUID) -> Optional[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.root_document_id == root_document_id)
        .order_by(Document.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _max_version(db: AsyncSession, root_document_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.max(Document.version)).where(Document.root_document_id == root_document_id)
    )
    return result.scalar() or 0


def _base_version_fields(
    origin_type: str,
    run_id: Optional[str],
    conversation_id: Optional[str],
    label: Optional[str],
) -> dict:
    return {
        "origin_type": origin_type,
        "origin_run_id": run_id,
        "origin_conversation_id": conversation_id,
        "origin_label": label,
    }


async def create_root_output(
    db: AsyncSession,
    *,
    user_id: Optional[uuid.UUID],
    file_type: str,
    origin_type: str,
    source_doc: Optional[Document] = None,
    original_filename: Optional[str] = None,
    content_bytes: Optional[bytes] = None,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    label: Optional[str] = None,
    doc_category: str = "output",
    extra_metadata: Optional[dict] = None,
) -> Document:
    """创建新 root 的输出文档 v1。

    文件来源优先级：content_bytes > 复制 source_doc 文件 > 不创建文件（调用方自行写入返回的路径）。
    """
    doc_id = uuid.uuid4()
    filename = (
        original_filename
        # 未显式指定文件名时按统一规则命名（源文件词干_操作_时间戳），不再与源文件同名
        or build_output_filename(
            source_doc.original_filename if source_doc else None, origin_type, file_type
        )
    )

    if content_bytes is not None:
        file_path, digest = file_storage.write_version_file(
            content_bytes, user_id, doc_category, doc_id, 1, filename
        )
    elif source_doc is not None and source_doc.file_path:
        file_path, digest = file_storage.copy_as_version(
            source_doc.file_path, user_id, doc_category, doc_id, 1, filename
        )
    else:
        file_path = str(file_storage.version_path(user_id, doc_category, doc_id, 1, filename))
        digest = None

    metadata = dict(extra_metadata or {})
    if source_doc is not None:
        metadata["derived_from"] = str(source_doc.id)

    doc = Document(
        id=doc_id,
        user_id=user_id,
        filename=os.path.basename(file_path),
        original_filename=filename,
        file_type=file_type,
        doc_category=doc_category,
        file_path=file_path,
        file_size=os.path.getsize(file_path) if digest else None,
        status="completed",
        root_document_id=doc_id,
        version=1,
        parent_version_id=None,
        sha256=digest,
        metadata_info=metadata,
        **_base_version_fields(origin_type, run_id, conversation_id, label),
    )
    db.add(doc)
    await db.flush()
    return doc


async def create_next_version(
    db: AsyncSession,
    prev_doc: Document,
    *,
    origin_type: str,
    run_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    label: Optional[str] = None,
    content_bytes: Optional[bytes] = None,
    file_source_path: Optional[str] = None,
) -> Document:
    """在 prev_doc 所属 root 下创建 version+1 新版本。

    文件来源优先级：content_bytes > file_source_path > 复制 prev_doc 文件。
    """
    root_id = prev_doc.root_document_id or prev_doc.id

    for attempt in range(MAX_VERSION_RETRIES):
        next_version = await _max_version(db, root_id) + 1
        if content_bytes is not None:
            file_path, digest = file_storage.write_version_file(
                content_bytes, prev_doc.user_id, prev_doc.doc_category,
                root_id, next_version, prev_doc.original_filename,
            )
        else:
            file_path, digest = file_storage.copy_as_version(
                file_source_path or prev_doc.file_path, prev_doc.user_id, prev_doc.doc_category,
                root_id, next_version, prev_doc.original_filename,
            )

        doc = Document(
            id=uuid.uuid4(),
            user_id=prev_doc.user_id,
            filename=os.path.basename(file_path),
            original_filename=prev_doc.original_filename,
            file_type=prev_doc.file_type,
            doc_category=prev_doc.doc_category,
            file_path=file_path,
            file_size=os.path.getsize(file_path),
            status="completed",
            root_document_id=root_id,
            version=next_version,
            parent_version_id=prev_doc.id,
            sha256=digest,
            metadata_info=dict(prev_doc.metadata_info or {}),
            **_base_version_fields(origin_type, run_id, conversation_id, label),
        )
        db.add(doc)
        try:
            await db.flush()
            return doc
        except IntegrityError:
            # (root_document_id, version) 并发冲突，回滚后重试
            await db.rollback()
            file_storage.remove_file_quietly(file_path)
            logger.warning("version insert conflict for root %s, retry %d", root_id, attempt + 1)

    raise RuntimeError(f"创建版本失败：root {root_id} 并发冲突超过 {MAX_VERSION_RETRIES} 次")


async def resolve_output_target(
    db: AsyncSession,
    doc: Document,
    *,
    run_id: Optional[str],
    origin_type: str,
    conversation_id: Optional[str] = None,
    label: Optional[str] = None,
) -> Tuple[Document, bool]:
    """决定本次修改的目标：同 run 原地改，新 run 创建新版本。

    Returns:
        (目标 Document, is_new_version)
        - is_new_version=False: 在原文件上修改（与改造前行为一致）
        - is_new_version=True: 返回的新行已持有复制好的版本文件，直接在其 file_path 上修改
    """
    if run_id and doc.origin_run_id == run_id:
        return doc, False
    new_doc = await create_next_version(
        db, doc,
        origin_type=origin_type,
        run_id=run_id,
        conversation_id=conversation_id,
        label=label,
    )
    return new_doc, True


async def replace_content_as_new_version(
    db: AsyncSession,
    doc: Document,
    content: bytes,
    *,
    origin_type: str,
) -> bool:
    """把 doc 的内容替换为 content：doc 行保持 id 成为最新版本，旧内容存为历史版本行。

    被编辑器/保存接口打开的文档 id 永远指向最新内容（聊天链接、预览面板不失效），
    旧文件/旧行在新文件写入前保持不动（崩溃安全）。

    Returns:
        True=产生了新版本，False=内容未变化（不产版本，防止重复保存刷版本）

    注意：只更新行并 flush，commit 由调用方负责。
    """
    new_digest = file_storage.sha256_bytes(content)
    old_path = doc.file_path
    current_digest = doc.sha256
    if not current_digest and old_path and os.path.exists(old_path):
        current_digest = file_storage.sha256_file(old_path)
    if new_digest == current_digest:
        return False

    root_id = doc.root_document_id or doc.id
    old_version = doc.version or 1
    old_parent = doc.parent_version_id
    old_origin = doc.origin_type

    new_version = await _max_version(db, root_id) + 1

    # 1. 被编辑行先升级为新版本号（腾出旧 version 号给历史行，避免唯一索引冲突）
    new_path = str(file_storage.version_path(
        doc.user_id, doc.doc_category, root_id, new_version, doc.original_filename
    ))
    doc.root_document_id = root_id
    doc.version = new_version
    doc.file_path = new_path
    await db.flush()

    # 2. 旧内容另存为历史版本行
    hist_id = None
    if old_path and os.path.exists(old_path):
        hist_path, _ = file_storage.copy_as_version(
            old_path, doc.user_id, doc.doc_category, root_id, old_version, doc.original_filename
        )
        hist = Document(
            id=uuid.uuid4(),
            user_id=doc.user_id,
            filename=os.path.basename(hist_path),
            original_filename=doc.original_filename,
            file_type=doc.file_type,
            doc_category=doc.doc_category,
            file_path=hist_path,
            file_size=os.path.getsize(hist_path),
            status="completed",
            root_document_id=root_id,
            version=old_version,
            parent_version_id=old_parent,
            origin_type=old_origin,
            sha256=current_digest,
            metadata_info=dict(doc.metadata_info or {}),
        )
        db.add(hist)
        await db.flush()
        hist_id = hist.id

    # 3. 新内容写入新版本路径
    with open(new_path, "wb") as f:
        f.write(content)

    # 4. 更新被编辑行为最新版本
    doc.parent_version_id = hist_id
    doc.origin_type = origin_type
    doc.file_size = len(content)
    doc.sha256 = new_digest
    doc.status = "updated"
    await db.flush()
    return True


def download_info(doc: Document) -> dict:
    """工具结果中统一的输出文件信息（保持 LLM 可见的键不变）"""
    return {
        "output_file_id": str(doc.id),
        "output_filename": doc.original_filename,
        "download_url": f"/api/v1/documents/{doc.id}/download",
    }

"""统一文件存储服务：所有文档文件的读写路径都经过这里。

目录布局：
    uploads/{user_id|"_shared"}/{sources|templates|docs}/{root_document_id}/v{version}_{安全文件名}

- sources/templates/docs 按 doc_category 分桶
- 每个逻辑文档（root）一个目录，目录名即 root_document_id，天然避免文件名冲突
- 版本文件以 v{n}_ 前缀区分，不再需要随机 uuid 前缀
"""

import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Optional, Tuple
from uuid import UUID

from app.core.config import get_settings

settings = get_settings()

_CATEGORY_BUCKETS = {
    "source": "sources",
    "template": "templates",
    "output": "docs",
}


def sanitize_filename(filename: str, default_suffix: str = ".docx") -> str:
    """清洗文件名，去除路径危险字符"""
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (filename or "").strip())
    clean = clean.strip(" ._") or f"unnamed{default_suffix}"
    if "." not in clean:
        clean = f"{clean}{default_suffix}"
    return clean


def user_dir(user_id: Optional[UUID | str]) -> str:
    return str(user_id) if user_id else "_shared"


def bucket_for_category(doc_category: str) -> str:
    return _CATEGORY_BUCKETS.get(doc_category, "docs")


def version_path(
    user_id: Optional[UUID | str],
    doc_category: str,
    root_document_id: UUID | str,
    version: int,
    original_filename: str,
) -> Path:
    """计算某个版本文件的存储路径（并确保父目录存在）"""
    safe_name = sanitize_filename(original_filename)
    path = (
        Path(settings.UPLOAD_DIR)
        / user_dir(user_id)
        / bucket_for_category(doc_category)
        / str(root_document_id)
        / f"v{version}_{safe_name}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def sha256_file(file_path: str | Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_version_file(
    content: bytes,
    user_id: Optional[UUID | str],
    doc_category: str,
    root_document_id: UUID | str,
    version: int,
    original_filename: str,
) -> Tuple[str, str]:
    """写入新版本文件，返回 (路径, sha256)"""
    path = version_path(user_id, doc_category, root_document_id, version, original_filename)
    with open(path, "wb") as f:
        f.write(content)
    return str(path), sha256_bytes(content)


def copy_as_version(
    src_path: str | Path,
    user_id: Optional[UUID | str],
    doc_category: str,
    root_document_id: UUID | str,
    version: int,
    original_filename: str,
) -> Tuple[str, str]:
    """复制已有文件为新版本文件，返回 (路径, sha256)"""
    path = version_path(user_id, doc_category, root_document_id, version, original_filename)
    shutil.copy2(src_path, path)
    return str(path), sha256_file(path)


def remove_file_quietly(file_path: Optional[str]) -> None:
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass

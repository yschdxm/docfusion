"""
OnlyOffice 服务 - 与 OnlyOffice Document Server 交互

功能：
- 调用 Command Service API 执行文档操作
- 触发 forcesave 命令
"""

import logging
import httpx
from typing import Optional
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class OnlyOfficeService:
    """OnlyOffice 服务"""

    def __init__(self):
        self.server_url = settings.ONLYOFFICE_DOCUMENT_SERVER_URL

    async def force_save(self, document_key: str) -> bool:
        """触发 OnlyOffice 强制保存

        Args:
            document_key: 文档的 key（由 _build_onlyoffice_document_key 生成）

        Returns:
            是否成功触发
        """
        try:
            url = f"{self.server_url}/command"
            payload = {
                "c": "forcesave",
                "key": document_key,
            }

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()

                result = response.json()
                if result.get("error") == 0:
                    logger.info(f"[OnlyOfficeService] force_save 成功 | key={document_key}")
                    return True
                else:
                    logger.error(f"[OnlyOfficeService] force_save 失败 | key={document_key}, error={result}")
                    return False

        except Exception as e:
            logger.exception(f"[OnlyOfficeService] force_save 异常 | key={document_key}, error={e}")
            return False

    async def get_document_info(self, document_key: str) -> Optional[dict]:
        """获取文档信息

        Args:
            document_key: 文档的 key

        Returns:
            文档信息，失败返回 None
        """
        try:
            url = f"{self.server_url}/command"
            payload = {
                "c": "info",
                "key": document_key,
            }

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()

                result = response.json()
                if result.get("error") == 0:
                    return result
                else:
                    logger.error(f"[OnlyOfficeService] get_document_info 失败 | key={document_key}, error={result}")
                    return None

        except Exception as e:
            logger.exception(f"[OnlyOfficeService] get_document_info 异常 | key={document_key}, error={e}")
            return None


# 全局实例
onlyoffice_service = OnlyOfficeService()

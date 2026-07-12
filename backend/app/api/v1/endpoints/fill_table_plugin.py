"""
填表插件通信 API

OnlyOffice 插件通过这些端点与后端通信，实现跨域填表数据传输。
"""

import asyncio
import logging
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
router = APIRouter()

# 内存存储：待处理的填表请求和结果
_pending_request: Optional[Dict[str, Any]] = None
_result_future: Optional[asyncio.Future] = None
_result_data: Optional[Dict[str, Any]] = None


class FillTableRequest(BaseModel):
    """填表请求"""
    headers: List[str]
    data: List[Dict[str, Any]]
    fill_mode: str = "overwrite"
    target_table_index: int = 0
    file_type: str = "xlsx"


class FillTableResult(BaseModel):
    """填表结果"""
    id: int
    success: bool
    error: Optional[str] = None
    filled: int = 0


@router.post("/submit")
async def submit_fill_request(request: FillTableRequest):
    """提交填表请求（由前端调用，等待插件处理）"""
    global _pending_request, _result_future, _result_data

    import time
    request_id = int(time.time() * 1000)

    _pending_request = {
        "id": request_id,
        "headers": request.headers,
        "data": request.data,
        "fillMode": request.fill_mode,
        "targetTableIndex": request.target_table_index,
        "fileType": request.file_type,
    }
    _result_data = None

    # 创建 Future 等待插件处理结果
    _result_future = asyncio.get_event_loop().create_future()

    logger.info(f"[FillTablePlugin] 提交填表请求 | id={request_id} | {len(request.data)}行")

    try:
        # 等待插件处理完成，最多30秒
        result = await asyncio.wait_for(_result_future, timeout=30)
        return {"success": True, "result": result}
    except asyncio.TimeoutError:
        logger.error(f"[FillTablePlugin] 填表超时 | id={request_id}")
        return {"success": False, "error": "填表超时（30秒）"}
    finally:
        _pending_request = None
        _result_future = None


@router.get("/pending")
async def get_pending_request():
    """获取待处理的填表请求（由 OnlyOffice 插件轮询调用）"""
    global _pending_request
    if _pending_request:
        return _pending_request
    return {"id": 0}


@router.post("/result")
async def submit_result(result: FillTableResult):
    """提交填表结果（由 OnlyOffice 插件调用）"""
    global _result_future, _result_data

    logger.info(f"[FillTablePlugin] 收到填表结果 | id={result.id} | success={result.success} | filled={result.filled}")

    _result_data = {
        "id": result.id,
        "success": result.success,
        "error": result.error,
        "filled": result.filled,
    }

    # 通知等待中的 Future
    if _result_future and not _result_future.done():
        _result_future.set_result(_result_data)

    return {"ok": True}

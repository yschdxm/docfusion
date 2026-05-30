"""文档预处理任务队列 — 限制并发任务数量，避免资源竞争和 LLM API 过载。

使用 asyncio.Semaphore 控制同时运行的任务数，默认最大并发为 3。
支持任务取消：删除文档时可以中断正在运行的预处理任务。
"""
import asyncio
import logging
from typing import Callable, Any, Dict

logger = logging.getLogger(__name__)

# 最大并发任务数
MAX_CONCURRENT_TASKS = 3

# 全局信号量，控制并发数
_task_semaphore: asyncio.Semaphore | None = None

# 等待队列中的任务数
_pending_count = 0
_running_count = 0

# 任务注册表：doc_id -> asyncio.Task
_running_tasks: Dict[str, asyncio.Task] = {}


def get_task_semaphore() -> asyncio.Semaphore:
    """获取或创建全局任务信号量。"""
    global _task_semaphore
    if _task_semaphore is None:
        _task_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
    return _task_semaphore


def get_queue_status() -> dict:
    """获取当前队列状态。"""
    return {
        "max_concurrent": MAX_CONCURRENT_TASKS,
        "running": _running_count,
        "pending": _pending_count,
    }


def cancel_task(doc_id: str) -> bool:
    """取消指定文档的预处理任务。

    Args:
        doc_id: 文档 ID

    Returns:
        是否成功取消
    """
    task = _running_tasks.get(doc_id)
    if task and not task.done():
        task.cancel()
        logger.info(f"[TASK_QUEUE] 已取消任务: doc_id={doc_id}")
        return True
    return False


async def enqueue_task(
    task_func: Callable,
    *args: Any,
    doc_id: str = None,
    task_name: str = "unknown",
    **kwargs: Any,
) -> Any:
    """将任务加入队列执行。

    使用信号量控制并发数，当达到最大并发时，任务会等待直到有空闲槽位。
    支持通过 doc_id 注册任务，以便后续取消。

    Args:
        task_func: 要执行的异步任务函数
        *args: 任务函数的位置参数
        doc_id: 文档 ID（用于任务取消）
        task_name: 任务名称（用于日志）
        **kwargs: 任务函数的关键字参数

    Returns:
        任务函数的返回值
    """
    global _pending_count, _running_count

    semaphore = get_task_semaphore()

    _pending_count += 1
    logger.info(f"[TASK_QUEUE] 任务入队: {task_name}, 当前等待: {_pending_count}, 运行中: {_running_count}")

    try:
        # 等待信号量（等待空闲槽位）
        async with semaphore:
            _pending_count -= 1
            _running_count += 1
            logger.info(f"[TASK_QUEUE] 任务开始: {task_name}, 当前运行中: {_running_count}")

            # 注册任务以便取消
            current_task = asyncio.current_task()
            if doc_id and current_task:
                _running_tasks[doc_id] = current_task

            try:
                result = await task_func(*args, **kwargs)
                return result
            except asyncio.CancelledError:
                logger.info(f"[TASK_QUEUE] 任务被取消: {task_name}")
                raise
            except Exception as e:
                logger.error(f"[TASK_QUEUE] 任务失败: {task_name}, 错误: {e}")
                raise
            finally:
                # 注销任务
                if doc_id:
                    _running_tasks.pop(doc_id, None)
                _running_count -= 1
                logger.info(f"[TASK_QUEUE] 任务结束: {task_name}, 当前运行中: {_running_count}")
    except asyncio.CancelledError:
        _pending_count -= 1
        if doc_id:
            _running_tasks.pop(doc_id, None)
        logger.warning(f"[TASK_QUEUE] 任务取消: {task_name}")
        raise

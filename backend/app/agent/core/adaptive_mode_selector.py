"""
自适应模式选择器 - 根据情况选择快速模式或普通模式

负责：
- 检测是否适合快速模式
- 超时自动降级
- 用户手动切换
"""

from typing import Dict, Any, Optional
import asyncio
import logging

from app.agent.core.fast_mode_detector import fast_mode_detector, FastModeDecision
from app.agent.core.fast_fill_table_agent import fast_fill_table_agent
from app.agent.core.stream import StreamManager
from app.agent.base.tool import ToolContext

logger = logging.getLogger(__name__)


class AdaptiveModeSelector:
    """自适应模式选择器

    根据情况选择快速模式或普通模式。
    """

    # 超时阈值（秒）
    FAST_MODE_TIMEOUT = 70

    async def select_and_execute(
        self,
        user_message: str,
        file_ids: list[str],
        template_id: Optional[str],
        context: ToolContext,
        stream_manager: StreamManager
    ) -> Dict[str, Any]:
        """选择模式并执行

        Args:
            user_message: 用户消息
            file_ids: 源文件ID列表
            template_id: 模板ID
            context: 工具上下文
            stream_manager: 流管理器

        Returns:
            执行结果
        """
        # 检查用户是否手动指定模式
        if user_message.startswith("/fast") or user_message.startswith("/快速"):
            logger.info("[AdaptiveModeSelector] 用户强制快速模式")
            return await self._execute_fast_mode(
                user_message, file_ids, template_id, context, stream_manager
            )
        elif user_message.startswith("/normal") or user_message.startswith("/普通"):
            logger.info("[AdaptiveModeSelector] 用户强制普通模式")
            return await self._execute_normal_mode(
                user_message, file_ids, template_id, context, stream_manager
            )

        # 检测是否适合快速模式
        decision = fast_mode_detector.detect(user_message, has_template=bool(template_id))

        if decision.use_fast_mode and decision.confidence >= 0.8:
            logger.info(f"[AdaptiveModeSelector] 使用快速模式 | 置信度: {decision.confidence}")
            try:
                # 带超时执行快速模式
                result = await asyncio.wait_for(
                    fast_fill_table_agent.execute(
                        user_message, file_ids, template_id, context, stream_manager, decision
                    ),
                    timeout=self.FAST_MODE_TIMEOUT
                )
                return result

            except asyncio.TimeoutError:
                logger.warning(f"[AdaptiveModeSelector] 快速模式超时，降级到普通模式")
                return await self._execute_normal_mode(
                    user_message, file_ids, template_id, context, stream_manager
                )
        else:
            logger.info(f"[AdaptiveModeSelector] 使用普通模式 | 原因: {decision.reason}")
            return await self._execute_normal_mode(
                user_message, file_ids, template_id, context, stream_manager
            )

    async def _execute_fast_mode(
        self,
        user_message: str,
        file_ids: list[str],
        template_id: Optional[str],
        context: ToolContext,
        stream_manager: StreamManager
    ) -> Dict[str, Any]:
        """执行快速模式"""
        decision = FastModeDecision(
            use_fast_mode=True,
            confidence=1.0,
            reason="用户强制快速模式",
            fast_agent_type="fill_table"
        )

        return await fast_fill_table_agent.execute(
            user_message, file_ids, template_id, context, stream_manager, decision
        )

    async def _execute_normal_mode(
        self,
        user_message: str,
        file_ids: list[str],
        template_id: Optional[str],
        context: ToolContext,
        stream_manager: StreamManager
    ) -> Dict[str, Any]:
        """执行普通模式"""
        from app.agent.core.initialization import get_orchestrator

        orchestrator = get_orchestrator()

        result = await orchestrator.dispatch(
            user_message=user_message,
            context=context,
            preferred_agent="table"
        )

        return result


# 全局自适应模式选择器实例
adaptive_mode_selector = AdaptiveModeSelector()

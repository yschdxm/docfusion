"""
快速模式检测器 - 检测是否适合快速模式

负责：
- 模式匹配检测
- 决策是否使用快速模式
"""

import re
from typing import Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class FastModeDecision:
    """快速模式决策"""
    use_fast_mode: bool
    confidence: float
    reason: str
    fast_agent_type: str  # "fill_table", "data_extract"


class FastModeDetector:
    """快速模式检测器

    通过模式匹配决定是否走快速路径。
    """

    # 填表相关模式
    FILL_TABLE_PATTERNS = [
        r'(填写|填充|填入|录入).*(表格|模板|表|Excel)',
        r'(根据|按照|依据).*(填写|填充|生成).*(表|Excel)',
        r'(把|将).*(数据|信息).*(填|写入).*(表|模板)',
        r'(自动|帮我).*(填写|填充|生成)',
        r'(提取|获取|读取).*(填|写入|生成)',
    ]

    def detect(
        self,
        user_message: str,
        has_template: bool = False
    ) -> FastModeDecision:
        """检测是否适合快速模式

        Args:
            user_message: 用户消息
            has_template: 是否已选中模板

        Returns:
            快速模式决策
        """
        # 检查模式匹配
        pattern_matched = any(
            re.search(pattern, user_message)
            for pattern in self.FILL_TABLE_PATTERNS
        )

        # 决策逻辑
        if has_template and pattern_matched:
            return FastModeDecision(
                use_fast_mode=True,
                confidence=0.95,
                reason="模板已选中且消息匹配填表模式",
                fast_agent_type="fill_table"
            )
        elif pattern_matched:
            return FastModeDecision(
                use_fast_mode=False,
                confidence=0.6,
                reason="消息匹配填表模式但未选中模板",
                fast_agent_type="fill_table"
            )
        else:
            return FastModeDecision(
                use_fast_mode=False,
                confidence=0.0,
                reason="消息不匹配快速模式",
                fast_agent_type=""
            )


# 全局快速模式检测器实例
fast_mode_detector = FastModeDetector()

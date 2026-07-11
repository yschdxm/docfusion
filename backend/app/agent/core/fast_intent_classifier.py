"""
快速意图分类器 - 轻量意图分类

负责：
- 快速分类用户意图
- 提取关键实体
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class IntentResult:
    """意图分类结果"""
    intent: str  # "fill_table", "query_data", "edit_document", "search", "other"
    data_source: str  # "pg", "neo4j", "rag", "auto"
    confidence: float
    extracted_entities: Dict[str, Any]


class FastIntentClassifier:
    """快速意图分类器

    轻量意图分类器，替代完整的LLM调用。
    """

    SYSTEM_PROMPT = """你是一个快速意图分类器。分析用户消息，返回JSON格式的分类结果。

返回格式：
{
    "intent": "fill_table|query_data|edit_document|search|other",
    "data_source": "pg|neo4j|rag|auto",
    "confidence": 0.0-1.0,
    "extracted_entities": {
        "template_hint": "模板相关提示",
        "data_hint": "数据相关提示"
    }
}

只返回JSON，不要其他内容。"""

    async def classify(self, user_message: str) -> IntentResult:
        """分类用户意图

        Args:
            user_message: 用户消息

        Returns:
            意图分类结果
        """
        from app.services.llm_service import llm_service

        prompt = f"""{self.SYSTEM_PROMPT}

用户消息：{user_message}"""

        try:
            response = await llm_service.generate(
                prompt=prompt,
                max_tokens=200,
                temperature=0
            )

            # 解析响应
            import json
            result = json.loads(response)

            return IntentResult(
                intent=result.get("intent", "other"),
                data_source=result.get("data_source", "auto"),
                confidence=result.get("confidence", 0.0),
                extracted_entities=result.get("extracted_entities", {})
            )

        except Exception as e:
            logger.error(f"意图分类失败: {e}")
            return IntentResult(
                intent="other",
                data_source="auto",
                confidence=0.0,
                extracted_entities={}
            )


# 全局快速意图分类器实例
fast_intent_classifier = FastIntentClassifier()

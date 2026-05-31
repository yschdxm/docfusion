"""错误恢复策略 - 工具失败时的自动降级

参考 OpenClaw 的错误恢复设计，提供：
- 工具降级链：当首选工具失败时自动切换到备选工具
- 失败原因分析：根据错误类型决定恢复策略
- 恢复建议生成：为 LLM 提供下一步行动建议
"""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


# 工具降级链：首选工具 -> 备选工具列表
TOOL_FALLBACK_CHAINS = {
    "query_pg_database": [
        "query_knowledge_graph",
        "rag_search",
        "extract_from_documents",
    ],
    "query_knowledge_graph": [
        "rag_search",
        "extract_from_documents",
    ],
    "rag_search": [
        "extract_from_documents",
    ],
    "extract_from_documents": [],  # 最后手段，无降级
    "get_table_structure": [],  # 结构查询无降级
    "fill_table": [],  # 填表操作无降级
}

# 错误类型分类
ERROR_CATEGORIES = {
    "connection": ["connection", "connect", "timeout", "超时", "网络", "network"],
    "rate_limit": ["rate_limit", "rate limit", "频率", "too many", "429"],
    "not_found": ["not found", "不存在", "未找到", "404", "no result"],
    "permission": ["permission", "forbidden", "权限", "403"],
    "invalid_input": ["invalid", "格式", "参数", "validation", "uuid"],
    "server_error": ["server error", "500", "internal", "服务"],
}


class ErrorRecoveryStrategy:
    """错误恢复策略"""

    @staticmethod
    def categorize_error(error: str) -> str:
        """将错误信息分类"""
        error_lower = error.lower()
        for category, keywords in ERROR_CATEGORIES.items():
            if any(kw in error_lower for kw in keywords):
                return category
        return "unknown"

    @staticmethod
    def get_fallback_tools(failed_tool: str) -> List[str]:
        """获取失败工具的降级工具列表"""
        return TOOL_FALLBACK_CHAINS.get(failed_tool, [])

    @staticmethod
    def build_fallback_suggestion(
        failed_tool: str,
        error: str,
        original_params: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """构建降级调用建议。

        Returns:
            None 表示无法降级，或包含 {tool_name, params, reason} 的降级建议
        """
        fallback_tools = ErrorRecoveryStrategy.get_fallback_tools(failed_tool)
        if not fallback_tools:
            return None

        error_category = ErrorRecoveryStrategy.categorize_error(error)
        next_tool = fallback_tools[0]

        # 根据失败工具和降级目标构建参数映射
        params = ErrorRecoveryStrategy._map_params(failed_tool, next_tool, original_params, error_category)
        if params is None:
            return None

        reason = ErrorRecoveryStrategy._build_reason(failed_tool, next_tool, error_category, error)

        logger.info(f"[ErrorRecovery] 降级建议: {failed_tool} -> {next_tool} | 原因: {reason}")

        return {
            "tool_name": next_tool,
            "params": params,
            "reason": reason,
            "original_tool": failed_tool,
            "error_category": error_category,
        }

    @staticmethod
    def _map_params(
        from_tool: str,
        to_tool: str,
        original_params: Dict[str, Any],
        error_category: str,
    ) -> Optional[Dict[str, Any]]:
        """映射工具参数：从失败工具的参数转换为降级工具的参数。"""

        # PG -> Neo4j
        if from_tool == "query_pg_database" and to_tool == "query_knowledge_graph":
            return {
                "query": original_params.get("query", ""),
                "doc_ids": original_params.get("doc_ids", []),
            }

        # PG -> RAG
        if from_tool == "query_pg_database" and to_tool == "rag_search":
            return {
                "query": original_params.get("query", ""),
                "doc_ids": original_params.get("doc_ids", []),
                "top_k": 10,
            }

        # PG -> extract
        if from_tool == "query_pg_database" and to_tool == "extract_from_documents":
            return {
                "doc_ids": original_params.get("doc_ids", []),
                "fields": original_params.get("fields", []),
                "max_records": original_params.get("max_rows", 50),
            }

        # Neo4j -> RAG
        if from_tool == "query_knowledge_graph" and to_tool == "rag_search":
            return {
                "query": original_params.get("query", ""),
                "doc_ids": original_params.get("doc_ids", []),
                "top_k": 10,
            }

        # Neo4j -> extract
        if from_tool == "query_knowledge_graph" and to_tool == "extract_from_documents":
            return {
                "doc_ids": original_params.get("doc_ids", []),
                "fields": original_params.get("fields", []),
                "max_records": original_params.get("max_records", 50),
            }

        # RAG -> extract
        if from_tool == "rag_search" and to_tool == "extract_from_documents":
            return {
                "doc_ids": original_params.get("doc_ids", []),
                "fields": original_params.get("fields", []),
                "max_records": original_params.get("max_records", 50),
            }

        # 通用：传递 doc_ids 和 query
        if "query" in original_params or "doc_ids" in original_params:
            return {
                "query": original_params.get("query", ""),
                "doc_ids": original_params.get("doc_ids", []),
            }

        return None

    @staticmethod
    def _build_reason(
        from_tool: str,
        to_tool: str,
        error_category: str,
        error: str,
    ) -> str:
        """构建降级原因说明"""
        tool_names = {
            "query_pg_database": "PostgreSQL查询",
            "query_knowledge_graph": "知识图谱查询",
            "rag_search": "RAG检索",
            "extract_from_documents": "文档提取",
        }

        from_name = tool_names.get(from_tool, from_tool)
        to_name = tool_names.get(to_tool, to_tool)

        reasons = {
            "connection": f"{from_name}连接失败，切换到{to_name}",
            "rate_limit": f"{from_name}频率限制，切换到{to_name}",
            "not_found": f"{from_name}未找到数据，尝试{to_name}",
            "server_error": f"{from_name}服务错误，切换到{to_name}",
        }

        return reasons.get(error_category, f"{from_name}失败({error[:50]})，切换到{to_name}")

    @staticmethod
    def build_recovery_prompt(failed_tool: str, error: str, original_params: Dict[str, Any]) -> str:
        """生成给 LLM 的恢复建议 prompt。"""
        suggestion = ErrorRecoveryStrategy.build_fallback_suggestion(failed_tool, error, original_params)

        if not suggestion:
            return (
                f"工具 {failed_tool} 执行失败: {error}\n"
                f"该工具没有可用的降级方案。请尝试：\n"
                f"1. 检查参数是否正确\n"
                f"2. 修改查询条件后重试\n"
                f"3. 向用户说明问题"
            )

        return (
            f"工具 {failed_tool} 执行失败: {error}\n"
            f"建议降级到 {suggestion['tool_name']}：{suggestion['reason']}\n"
            f"请使用 {suggestion['tool_name']} 工具重试。"
        )

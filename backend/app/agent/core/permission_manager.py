"""
权限管理器 - 管理工具执行权限

负责：
- 权限级别判定
- 用户偏好检查
- 审批流程管理
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
import logging

from app.agent.base.tool import PermissionLevel

logger = logging.getLogger(__name__)


class PermissionDecision(str, Enum):
    """权限决策"""
    ALLOW = "allow"                    # 允许执行
    ASK = "ask"                        # 询问用户
    REQUIRE_CONFIRMATION = "require_confirmation"  # 必须确认
    DENY = "deny"                      # 拒绝执行


@dataclass
class ApprovalRequest:
    """审批请求"""
    request_id: str
    tool_name: str
    tool_params: Dict[str, Any]
    permission_level: PermissionLevel
    description: str
    warnings: List[str]
    changes_preview: Optional[Dict[str, Any]] = None


@dataclass
class ApprovalResponse:
    """审批响应"""
    request_id: str
    approved: bool
    modified_params: Optional[Dict[str, Any]] = None
    user_message: Optional[str] = None


class PermissionManager:
    """权限管理器

    管理工具执行权限，支持三级权限和用户偏好。
    """

    # 安全工具列表（自动执行）
    SAFE_TOOLS = {
        "read_document", "read_cell_range", "read_selection",
        "list_documents", "get_document_info", "search_in_document",
        "query_pg_database", "query_knowledge_graph", "rag_search",
        "get_table_structure", "get_entity_details",
        "search_documents", "web_search", "natural_language_query",
        "aggregate_data", "auto_fill_suggestions",
        "find_related_entities", "ask_user", "show_notification",
        "get_current_time", "create_task", "get_task_status",
        "generate_preview"
    }

    # 危险工具列表（必须确认）
    DANGEROUS_TOOLS = {
        "delete_content", "merge_cells", "split_cell",
        "apply_template_style"
    }

    def __init__(self):
        self._auto_approved_tools: set = set()

    def check_permission(
        self,
        tool_name: str,
        tool_params: Dict[str, Any],
        permission_level: PermissionLevel
    ) -> PermissionDecision:
        """检查工具执行权限

        Args:
            tool_name: 工具名称
            tool_params: 工具参数
            permission_level: 权限级别

        Returns:
            权限决策
        """
        # 安全工具 - 自动执行
        if tool_name in self.SAFE_TOOLS or permission_level == PermissionLevel.SAFE:
            return PermissionDecision.ALLOW

        # 危险工具 - 必须确认
        if tool_name in self.DANGEROUS_TOOLS or permission_level == PermissionLevel.DANGEROUS:
            return PermissionDecision.REQUIRE_CONFIRMATION

        # 敏感工具 - 检查用户偏好
        if tool_name in self._auto_approved_tools:
            return PermissionDecision.ALLOW

        return PermissionDecision.ASK

    def auto_approve_tool(self, tool_name: str) -> None:
        """自动批准工具（用户设置）

        Args:
            tool_name: 工具名称
        """
        self._auto_approved_tools.add(tool_name)
        logger.info(f"自动批准工具: {tool_name}")

    def revoke_auto_approval(self, tool_name: str) -> None:
        """撤销自动批准

        Args:
            tool_name: 工具名称
        """
        self._auto_approved_tools.discard(tool_name)
        logger.info(f"撤销自动批准: {tool_name}")

    def create_approval_request(
        self,
        tool_name: str,
        tool_params: Dict[str, Any],
        permission_level: PermissionLevel
    ) -> ApprovalRequest:
        """创建审批请求

        Args:
            tool_name: 工具名称
            tool_params: 工具参数
            permission_level: 权限级别

        Returns:
            审批请求
        """
        import uuid

        # 生成描述
        description = self._generate_description(tool_name, tool_params)

        # 生成警告
        warnings = self._generate_warnings(tool_name, permission_level)

        # 生成变更预览
        changes_preview = self._generate_changes_preview(tool_name, tool_params)

        return ApprovalRequest(
            request_id=str(uuid.uuid4()),
            tool_name=tool_name,
            tool_params=tool_params,
            permission_level=permission_level,
            description=description,
            warnings=warnings,
            changes_preview=changes_preview
        )

    def _generate_description(self, tool_name: str, tool_params: Dict[str, Any]) -> str:
        """生成操作描述"""
        # 根据工具类型生成描述
        if "replace" in tool_name:
            old_text = tool_params.get("old_text", "")
            new_text = tool_params.get("new_text", "")
            return f"替换文本: '{old_text[:30]}...' → '{new_text[:30]}...'"
        elif "fill" in tool_name:
            return f"填写表格"
        elif "delete" in tool_name:
            return f"删除内容"
        elif "rewrite" in tool_name:
            return f"重写段落"
        elif "convert" in tool_name:
            target_format = tool_params.get("format", "")
            return f"转换格式为 {target_format}"
        elif "export" in tool_name:
            target_format = tool_params.get("format", "")
            return f"导出为 {target_format} 格式"
        elif "batch" in tool_name:
            operations = tool_params.get("operations", [])
            return f"批量执行 {len(operations)} 个操作"
        else:
            return f"执行操作: {tool_name}"

    def _generate_warnings(self, tool_name: str, permission_level: PermissionLevel) -> List[str]:
        """生成警告信息"""
        warnings = []

        if permission_level == PermissionLevel.DANGEROUS:
            warnings.append("此操作将修改文档内容，可能不可逆")

        if "delete" in tool_name:
            warnings.append("删除操作无法撤销")

        if "merge" in tool_name:
            warnings.append("合并单元格将影响表格结构")

        if "split" in tool_name:
            warnings.append("拆分单元格将影响表格结构")

        if "apply_template_style" in tool_name:
            warnings.append("应用模板样式将覆盖现有样式")

        if "batch" in tool_name:
            warnings.append("批量操作将一次性执行多个修改")

        return warnings

    def _generate_changes_preview(self, tool_name: str, tool_params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """生成变更预览"""
        # 根据工具类型生成预览
        if "replace" in tool_name:
            return {
                "type": "text_change",
                "before": tool_params.get("old_text", ""),
                "after": tool_params.get("new_text", "")
            }
        elif "fill_cell" in tool_name:
            return {
                "type": "cell_change",
                "row": tool_params.get("row"),
                "col": tool_params.get("col"),
                "value": tool_params.get("value")
            }
        elif "fill_row" in tool_name:
            return {
                "type": "row_change",
                "row": tool_params.get("row"),
                "data": tool_params.get("data", [])
            }
        elif "fill_column" in tool_name:
            return {
                "type": "column_change",
                "col": tool_params.get("col"),
                "data": tool_params.get("data", [])
            }
        return None


# 全局权限管理器实例
permission_manager = PermissionManager()

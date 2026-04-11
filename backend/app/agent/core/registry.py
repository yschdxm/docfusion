"""
工具注册表 - 管理所有可用工具

参考OpenClaw的Tools系统设计，提供：
- 工具注册和发现
- 工具权限控制 (allow/deny lists)
- 工具分组管理
- 工具schema生成
"""

from typing import Dict, List, Any, Optional, Set
from app.agent.base.tool import BaseTool


class ToolRegistry:
    """工具注册表

    管理所有可用的工具，支持权限控制和分组管理。
    类似于OpenClaw的工具配置系统。
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._allow_list: Optional[Set[str]] = None
        self._deny_list: Set[str] = set()

    def register(self, tool: BaseTool) -> None:
        """注册一个工具"""
        self._tools[tool.name] = tool

    def register_many(self, tools: List[BaseTool]) -> None:
        """批量注册工具"""
        for tool in tools:
            self.register(tool)

    def unregister(self, tool_name: str) -> None:
        """注销一个工具"""
        if tool_name in self._tools:
            del self._tools[tool_name]

    def get(self, tool_name: str) -> Optional[BaseTool]:
        """获取指定名称的工具"""
        return self._tools.get(tool_name)

    def list_tools(self, include_disabled: bool = False) -> List[str]:
        """列出所有可用工具名称

        Args:
            include_disabled: 是否包含被禁用的工具

        Returns:
            工具名称列表
        """
        tools = list(self._tools.keys())

        if not include_disabled:
            # 应用deny列表
            tools = [t for t in tools if t not in self._deny_list]

            # 应用allow列表
            if self._allow_list is not None:
                tools = [t for t in tools if t in self._allow_list]

        return tools

    def get_all_tools(self, include_disabled: bool = False) -> List[BaseTool]:
        """获取所有可用工具实例"""
        tool_names = self.list_tools(include_disabled=include_disabled)
        return [self._tools[name] for name in tool_names if name in self._tools]

    def get_function_schemas(self, include_disabled: bool = False) -> List[Dict[str, Any]]:
        """获取所有可用工具的Function Calling schemas"""
        tools = self.get_all_tools(include_disabled=include_disabled)
        return [tool.to_function_schema() for tool in tools]

    def get_tool_schemas(self, include_disabled: bool = False) -> List[Dict[str, Any]]:
        """获取所有可用工具的JSON schemas (用于前端展示)"""
        tools = self.get_all_tools(include_disabled=include_disabled)
        return [tool.to_json() for tool in tools]

    def set_allow_list(self, tools: List[str]) -> None:
        """设置允许列表，只有列表中的工具可用

        类似于OpenClaw的 tools.allow 配置
        """
        self._allow_list = set(tools)

    def set_deny_list(self, tools: List[str]) -> None:
        """设置禁止列表，列表中的工具不可用

        类似于OpenClaw的 tools.deny 配置
        deny优先级高于allow
        """
        self._deny_list = set(tools)

    def clear_lists(self) -> None:
        """清除允许和禁止列表"""
        self._allow_list = None
        self._deny_list = set()

    def is_tool_allowed(self, tool_name: str) -> bool:
        """检查工具是否被允许使用"""
        # 检查deny列表
        if tool_name in self._deny_list:
            return False

        # 检查allow列表
        if self._allow_list is not None:
            return tool_name in self._allow_list

        return True

    def get_tool_groups(self) -> Dict[str, List[str]]:
        """获取工具分组

        类似于OpenClaw的 group:* 系统
        """
        groups = {
            "group:data_query": [],    # 数据查询工具
            "group:document": [],      # 文档操作工具
            "group:retrieval": [],     # 检索工具
        }

        for tool_name in self.list_tools():
            if "query" in tool_name or "search" in tool_name:
                groups["group:data_query"].append(tool_name)
            if "doc" in tool_name or "table" in tool_name:
                groups["group:document"].append(tool_name)
            if "rag" in tool_name or "extract" in tool_name:
                groups["group:retrieval"].append(tool_name)

        return groups

    def __contains__(self, tool_name: str) -> bool:
        """检查是否包含指定工具"""
        return tool_name in self._tools

    def __len__(self) -> int:
        """返回注册的工具数量"""
        return len(self._tools)


# 全局工具注册表实例
tool_registry = ToolRegistry()

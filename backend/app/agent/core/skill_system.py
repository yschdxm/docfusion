"""
Skill系统 - 可复用的工作流模板

负责：
- 注册Skill模板
- 匹配用户意图
- 应用Skill配置
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import re
import logging

logger = logging.getLogger(__name__)


@dataclass
class SkillDefinition:
    """Skill定义"""
    name: str                          # 唯一标识符
    display_name: str                  # 显示名称
    description: str                   # 描述
    category: str                      # 分类
    trigger_patterns: List[str]        # 触发模式（正则列表）
    trigger_keywords: List[str]        # 触发关键词列表
    target_agent: str                  # 目标Agent类型
    system_prompt_addon: str           # 附加系统提示词
    required_tools: List[str]          # 必需工具列表
    parameter_templates: Dict[str, Any] = field(default_factory=dict)  # 参数模板
    examples: List[str] = field(default_factory=list)  # 使用示例


class SkillRegistry:
    """Skill注册表

    管理所有Skill模板，提供匹配功能。
    """

    def __init__(self):
        self._skills: Dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        """注册Skill

        Args:
            skill: Skill定义
        """
        self._skills[skill.name] = skill
        logger.info(f"注册Skill: {skill.name} ({skill.display_name})")

    def match(self, user_message: str) -> List[SkillDefinition]:
        """匹配用户消息

        Args:
            user_message: 用户消息

        Returns:
            匹配的Skill列表
        """
        matched_skills = []

        for skill in self._skills.values():
            # 检查关键词
            keyword_matched = any(kw in user_message for kw in skill.trigger_keywords)

            # 检查正则模式
            pattern_matched = any(
                re.search(pattern, user_message)
                for pattern in skill.trigger_patterns
            )

            if keyword_matched or pattern_matched:
                matched_skills.append(skill)

        return matched_skills

    def get(self, name: str) -> Optional[SkillDefinition]:
        """获取Skill定义

        Args:
            name: Skill名称

        Returns:
            Skill定义，如果不存在返回None
        """
        return self._skills.get(name)

    def list_skills(self) -> List[str]:
        """列出所有Skill名称

        Returns:
            Skill名称列表
        """
        return list(self._skills.keys())


def register_builtin_skills(skill_registry: SkillRegistry) -> None:
    """注册内置Skill

    Args:
        skill_registry: Skill注册表
    """
    # 1. 总结文档
    skill_registry.register(SkillDefinition(
        name="summarize_document",
        display_name="总结文档",
        description="对文档内容进行总结和概括",
        category="document",
        trigger_patterns=[r"总结.*文档", r"概括.*内容"],
        trigger_keywords=["总结", "摘要", "概括", "summarize"],
        target_agent="editor",
        system_prompt_addon="请对文档内容进行总结，提取关键信息和要点。",
        required_tools=["read_document", "rag_search"],
        examples=["总结这个文档的主要内容", "请帮我概括一下这篇文章"]
    ))

    # 2. 翻译文档
    skill_registry.register(SkillDefinition(
        name="translate_document",
        display_name="翻译文档",
        description="将文档内容翻译为指定语言",
        category="document",
        trigger_patterns=[r"翻译.*文档", r"translate.*document"],
        trigger_keywords=["翻译", "translate"],
        target_agent="editor",
        system_prompt_addon="请将文档内容翻译为用户指定的语言。",
        required_tools=["read_document"],
        examples=["将这个文档翻译成英文", "请帮我翻译这段内容"]
    ))

    # 3. 格式化报告
    skill_registry.register(SkillDefinition(
        name="format_report",
        display_name="格式化报告",
        description="对报告进行格式化和美化",
        category="document",
        trigger_patterns=[r"格式化.*报告", r"排版.*文档"],
        trigger_keywords=["格式化", "排版", "美化", "format"],
        target_agent="editor",
        system_prompt_addon="请对报告进行格式化，使其更加美观和专业。",
        required_tools=["read_document", "replace_text", "set_text_style"],
        examples=["格式化这个报告", "请帮我美化一下这个文档"]
    ))

    # 4. 提取表格数据
    skill_registry.register(SkillDefinition(
        name="extract_table_data",
        display_name="提取表格数据",
        description="从文档中提取表格数据",
        category="data",
        trigger_patterns=[r"提取.*表格", r"导出.*数据"],
        trigger_keywords=["提取表格", "导出数据", "extract"],
        target_agent="data",
        system_prompt_addon="请从文档中提取表格数据，并以结构化格式返回。",
        required_tools=["read_document", "query_pg_database"],
        examples=["提取这个文档中的表格", "请帮我导出这些数据"]
    ))

    # 5. 填写模板
    skill_registry.register(SkillDefinition(
        name="fill_template",
        display_name="填写模板",
        description="使用数据填写模板表格",
        category="table",
        trigger_patterns=[r"填写.*模板", r"填充.*表格"],
        trigger_keywords=["填写模板", "填充表格", "fill"],
        target_agent="table",
        system_prompt_addon="请使用提供的数据填写模板表格。",
        required_tools=["get_table_structure", "fill_table"],
        examples=["填写这个模板", "请帮我填充这个表格"]
    ))

    # 6. 对比文档
    skill_registry.register(SkillDefinition(
        name="compare_documents",
        display_name="对比文档",
        description="对比两个文档的差异",
        category="search",
        trigger_patterns=[r"对比.*文档", r"比较.*差异"],
        trigger_keywords=["对比", "比较", "差异", "compare"],
        target_agent="search",
        system_prompt_addon="请对比两个文档，找出它们之间的差异。",
        required_tools=["read_document", "search_documents"],
        examples=["对比这两个文档", "请帮我比较一下这两个文件"]
    ))

    # 7. 构建实体图谱
    skill_registry.register(SkillDefinition(
        name="build_entity_graph",
        display_name="构建实体图谱",
        description="从文档中提取实体关系，构建知识图谱",
        category="knowledge",
        trigger_patterns=[r"构建.*图谱", r"实体.*关系"],
        trigger_keywords=["构建图谱", "实体关系", "graph"],
        target_agent="knowledge",
        system_prompt_addon="请从文档中提取实体和关系，构建知识图谱。",
        required_tools=["build_knowledge_graph"],
        examples=["构建这个文档的知识图谱", "请帮我提取实体关系"]
    ))

    # 8. 生成汇总表
    skill_registry.register(SkillDefinition(
        name="generate_summary_table",
        display_name="生成汇总表",
        description="根据数据生成汇总统计表",
        category="table",
        trigger_patterns=[r"生成.*汇总", r"统计.*表"],
        trigger_keywords=["生成汇总", "统计表", "summary"],
        target_agent="table",
        system_prompt_addon="请根据数据生成汇总统计表。",
        required_tools=["aggregate_data", "fill_table"],
        examples=["生成一个汇总表", "请帮我统计一下这些数据"]
    ))

    logger.info(f"已注册 {len(skill_registry.list_skills())} 个内置Skill")

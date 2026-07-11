"""
SkillSystem 测试
"""

import pytest
from app.agent.core.skill_system import (
    SkillRegistry,
    SkillDefinition,
    register_builtin_skills
)


class TestSkillRegistry:
    """SkillRegistry 测试"""

    @pytest.fixture
    def registry(self):
        return SkillRegistry()

    def test_register(self, registry):
        skill = SkillDefinition(
            name="test_skill",
            display_name="Test Skill",
            description="A test skill",
            category="test",
            trigger_patterns=[],
            trigger_keywords=["test"],
            target_agent="editor",
            system_prompt_addon="",
            required_tools=[]
        )
        registry.register(skill)
        assert "test_skill" in registry.list_skills()

    def test_match_keyword(self, registry):
        skill = SkillDefinition(
            name="summarize",
            display_name="Summarize",
            description="Summarize document",
            category="document",
            trigger_patterns=[],
            trigger_keywords=["总结", "摘要"],
            target_agent="editor",
            system_prompt_addon="",
            required_tools=[]
        )
        registry.register(skill)

        matched = registry.match("请帮我总结这个文档")
        assert len(matched) == 1
        assert matched[0].name == "summarize"

    def test_match_pattern(self, registry):
        skill = SkillDefinition(
            name="translate",
            display_name="Translate",
            description="Translate document",
            category="document",
            trigger_patterns=[r"翻译.*文档"],
            trigger_keywords=[],
            target_agent="editor",
            system_prompt_addon="",
            required_tools=[]
        )
        registry.register(skill)

        matched = registry.match("请把这个文档翻译成英文")
        assert len(matched) == 1
        assert matched[0].name == "translate"

    def test_no_match(self, registry):
        skill = SkillDefinition(
            name="summarize",
            display_name="Summarize",
            description="Summarize document",
            category="document",
            trigger_patterns=[],
            trigger_keywords=["总结"],
            target_agent="editor",
            system_prompt_addon="",
            required_tools=[]
        )
        registry.register(skill)

        matched = registry.match("请帮我填写表格")
        assert len(matched) == 0

    def test_multiple_matches(self, registry):
        skill1 = SkillDefinition(
            name="skill1",
            display_name="Skill 1",
            description="Skill 1",
            category="test",
            trigger_patterns=[],
            trigger_keywords=["test"],
            target_agent="editor",
            system_prompt_addon="",
            required_tools=[]
        )
        skill2 = SkillDefinition(
            name="skill2",
            display_name="Skill 2",
            description="Skill 2",
            category="test",
            trigger_patterns=[r"test.*skill"],
            trigger_keywords=["test"],
            target_agent="editor",
            system_prompt_addon="",
            required_tools=[]
        )
        registry.register(skill1)
        registry.register(skill2)

        matched = registry.match("test skill")
        assert len(matched) == 2

    def test_get_skill(self, registry):
        skill = SkillDefinition(
            name="test_skill",
            display_name="Test Skill",
            description="A test skill",
            category="test",
            trigger_patterns=[],
            trigger_keywords=["test"],
            target_agent="editor",
            system_prompt_addon="",
            required_tools=[]
        )
        registry.register(skill)

        result = registry.get("test_skill")
        assert result is not None
        assert result.name == "test_skill"

    def test_get_nonexistent(self, registry):
        result = registry.get("nonexistent")
        assert result is None


class TestBuiltinSkills:
    """内置Skill测试"""

    def test_register_all(self):
        registry = SkillRegistry()
        register_builtin_skills(registry)

        skills = registry.list_skills()
        assert len(skills) == 8
        assert "summarize_document" in skills
        assert "translate_document" in skills
        assert "format_report" in skills
        assert "extract_table_data" in skills
        assert "fill_template" in skills
        assert "compare_documents" in skills
        assert "build_entity_graph" in skills
        assert "generate_summary_table" in skills

    def test_summarize_document(self):
        registry = SkillRegistry()
        register_builtin_skills(registry)

        matched = registry.match("请帮我总结这个文档")
        assert len(matched) >= 1
        assert any(s.name == "summarize_document" for s in matched)

    def test_translate_document(self):
        registry = SkillRegistry()
        register_builtin_skills(registry)

        matched = registry.match("请把这个文档翻译成英文")
        assert len(matched) >= 1
        assert any(s.name == "translate_document" for s in matched)

    def test_fill_template(self):
        registry = SkillRegistry()
        register_builtin_skills(registry)

        matched = registry.match("请帮我填写这个模板")
        assert len(matched) >= 1
        assert any(s.name == "fill_template" for s in matched)

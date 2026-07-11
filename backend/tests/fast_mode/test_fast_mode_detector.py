"""
FastModeDetector 测试
"""

import pytest
from app.agent.core.fast_mode_detector import FastModeDetector, FastModeDecision


class TestFastModeDetector:
    """FastModeDetector 测试"""

    @pytest.fixture
    def detector(self):
        return FastModeDetector()

    def test_detect_fill_table_with_template(self, detector):
        decision = detector.detect("请帮我填写这个表格", has_template=True)
        assert decision.use_fast_mode is True
        assert decision.confidence == 0.95
        assert decision.fast_agent_type == "fill_table"

    def test_detect_fill_table_without_template(self, detector):
        decision = detector.detect("请帮我填写这个表格", has_template=False)
        assert decision.use_fast_mode is False
        assert decision.confidence == 0.6

    def test_detect_no_match(self, detector):
        decision = detector.detect("请帮我查询数据")
        assert decision.use_fast_mode is False
        assert decision.confidence == 0.0
        assert decision.fast_agent_type == ""

    def test_detect_patterns(self, detector):
        # 测试各种模式
        patterns = [
            "填写表格",
            "填充模板",
            "把数据填入表中",
            "帮我自动生成",
            "提取数据填写"
        ]

        for pattern in patterns:
            decision = detector.detect(pattern, has_template=True)
            assert decision.use_fast_mode is True, f"Pattern failed: {pattern}"

    def test_detect_case_insensitive(self, detector):
        # 测试大小写不敏感
        decision = detector.detect("请帮我填写这个表格", has_template=True)
        assert decision.use_fast_mode is True

    def test_decision_dataclass(self, detector):
        decision = detector.detect("请帮我填写这个表格", has_template=True)
        assert isinstance(decision, FastModeDecision)
        assert hasattr(decision, 'use_fast_mode')
        assert hasattr(decision, 'confidence')
        assert hasattr(decision, 'reason')
        assert hasattr(decision, 'fast_agent_type')

"""
测试配置和基础fixture
"""

import pytest
import asyncio
from typing import AsyncGenerator


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_file_ids():
    """示例文件ID列表"""
    return ["test-file-id-1", "test-file-id-2"]


@pytest.fixture
def sample_template_id():
    """示例模板ID"""
    return "test-template-id"


@pytest.fixture
def sample_user_message():
    """示例用户消息"""
    return "请帮我填写这个表格"

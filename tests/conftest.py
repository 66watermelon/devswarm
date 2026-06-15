"""
DevSwarm 测试共享 Fixtures

所有测试自动加载。提供 mock LLM、构建 test state 的辅助函数。
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Optional
from langchain_core.messages import (
    HumanMessage, AIMessage, SystemMessage, ToolMessage,
)


# ================================================================
# Mock LLM —— 拦截所有 LLM 调用
# ================================================================

@pytest.fixture
def mock_llm():
    """固定返回 AIMessage 的 mock LLM。"""
    llm = MagicMock()
    llm.invoke = MagicMock(return_value=AIMessage(
        content="mock response",
        name="analyst",
    ))
    return llm


@pytest.fixture
def mock_structured_llm():
    """mock 结构化输出。"""
    from pydantic import BaseModel

    class MockOutput(BaseModel):
        mode: str = "solve"
        current_topic: Optional[str] = "数组"

    llm = MagicMock()
    llm.invoke = MagicMock(return_value=MockOutput())
    return llm


# ================================================================
# Test State 构建工具
# ================================================================

def build_test_state(
    mode: str = "solve",
    problem: str = "用Python写两数之和",
    user_code: str = "",
    generated_code: str = "",
    retry_count: int = 0,
    execution_feedback: str = "",
    algorithm_strategy: str = "",
    edge_cases: str = "",
    user_memory_context: str = "",
    current_topic: Optional[str] = None,
    user_id: int = 1,
    messages: Optional[list] = None,
) -> dict:
    """构建完整的 DevState 字典。"""
    if messages is None:
        messages = [HumanMessage(content=problem)]
    return {
        "messages": messages,
        "problem_description": problem,
        "user_code": user_code,
        "algorithm_strategy": algorithm_strategy,
        "edge_cases": edge_cases,
        "generated_code": generated_code,
        "execution_feedback": execution_feedback,
        "final_explanation": "",
        "retry_count": retry_count,
        "mode": mode,
        "user_id": user_id,
        "current_topic": current_topic,
        "user_memory_context": user_memory_context,
        "diagnose_report": "",
    }


def make_human_messages(*contents: str) -> list:
    """快速构建 HumanMessage 列表。"""
    return [HumanMessage(content=c) for c in contents]

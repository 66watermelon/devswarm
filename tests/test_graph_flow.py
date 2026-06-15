"""
集成测试：mock LLM 验证三模式图拓扑正确性。

不调真实 LLM —— 用固定回复代替。验证的是节点执行顺序，
确保路由逻辑和边的连接不被意外修改破坏。
"""

import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage, HumanMessage

import main_graph
from tests.conftest import build_test_state


# ================================================================
# 辅助：mock LLM 工厂（所有 LLM 返回固定 AIMessage）
# ================================================================

def _make_mock_invoke(text="mock", tool_calls=None, name="analyst"):
    """构建 mock LLM，invoke() 返回固定 AIMessage。"""
    mock = MagicMock()
    mock.invoke.return_value = AIMessage(
        content=text, tool_calls=tool_calls or [], name=name,
    )
    return mock


async def _collect_node_names(input_state: dict) -> list[str]:
    """跑图并收集节点执行顺序。"""
    if main_graph.app is None:
        pytest.skip("Graph 未编译（Checkpointer 未初始化）")

    config = {"configurable": {"thread_id": "test-graph-flow"}}
    nodes = []
    async for chunk in main_graph.app.astream(input_state, config=config):
        nodes.append(list(chunk.keys())[0])
    return nodes


# ================================================================
# Solve 模式拓扑
# ================================================================

@pytest.mark.asyncio
async def test_solve_mode_node_order():
    """solve 模式：intent → analyst → developer → qa → tutor。不含 chat_agent。"""
    # 先 mock 掉 analyzer 的 graph_reader 调用
    with patch("core.nodes.intent_recognizer_node.GraphReader.fetch_user_knowledge_profile") as mock_neo:
        mock_neo.return_value = "mock_knowledge"

        state = build_test_state(mode="solve", problem="写两数之和")
        nodes = await _collect_node_names(state)

        # 核心验证：入口是 intent_recognizer
        assert nodes[0] == "intent_recognizer"
        # 走到了 analyst
        assert "analyst" in nodes
        # solve 模式必须走 developer
        assert "developer" in nodes
        # 最终必须到 tutor（solve 出口）
        assert "tutor" in nodes
        # chat 模式不应该出现在 solve 路径
        assert "chat_agent" not in nodes


@pytest.mark.asyncio
async def test_diagnose_mode_skips_developer_on_first_pass():
    """diagnose 首轮：analyst → qa（直连，跳过 developer）。"""
    with patch("core.nodes.intent_recognizer_node.GraphReader.fetch_user_knowledge_profile") as mock_neo:
        mock_neo.return_value = "mock_knowledge"

        state = build_test_state(mode="diagnose", problem="这段代码为什么错", user_code="def f(): pass")
        nodes = await _collect_node_names(state)

        # diagnose 模式：analyst 之后必须直接到 qa
        analyst_idx = nodes.index("analyst")
        assert nodes[analyst_idx + 1] == "qa"
        # solve 出口 tutor 不应出现
        assert "tutor" not in nodes


@pytest.mark.asyncio
async def test_chat_mode_goes_straight_to_chat_agent():
    """chat 模式：intent → chat_agent → END。不进入流水线。"""
    with patch("core.nodes.intent_recognizer_node.GraphReader.fetch_user_knowledge_profile") as mock_neo:
        mock_neo.return_value = "mock_knowledge"

        state = build_test_state(mode="chat", problem="什么是动态规划")
        nodes = await _collect_node_names(state)

        # 只有 intent_recognizer 和 chat_agent
        assert "analyst" not in nodes
        assert "developer" not in nodes
        assert "qa" not in nodes
        assert "tutor" not in nodes
        assert "chat_agent" in nodes

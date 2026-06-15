"""
DevSwarm 算法推演平台 —— 主执行图 (Main Graph)

本文件负责：
1. 构建 LangGraph StateGraph，连接 6 个 Agent 节点。
2. 实现意图识别路由：task → 解题流水线 / chat → 答疑分支。
3. 定义条件路由逻辑（模式分发、QA 判题门禁）。
4. 注册 Developer / QA 的工具节点并配置回传环路。
5. 编译图并暴露可调用的 app 实例（注入 PostgreSQL 长期记忆）。
"""

from typing import Optional

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
# 【修改】从 SQLite 变更为 PostgreSQL 检查点
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from core.engine.state import DevState
from core.nodes import (
    intent_recognizer_node,
    analyst_node,
    developer_node,
    qa_node,
    tutor_node,
    chat_agent_node,
)
from core.tools import (
    read_workspace_file,
    write_workspace_file,
    list_workspace_files,
)
from core.tools.sandbox_tool import run_sandbox_test
from core.tools.recommendation_tool import recommend_topics
# 【新增】干净地导入我们刚刚建好的物理连接池
from db.postgres_client import pg_pool

# ---------------------------------------------------------------------------
# 工具注册 —— 按角色拆分
# ---------------------------------------------------------------------------
_DEV_TOOLS = [read_workspace_file, write_workspace_file, list_workspace_files]
_QA_TOOLS = [read_workspace_file, write_workspace_file, run_sandbox_test]
_CHAT_TOOLS = [recommend_topics]


# ---------------------------------------------------------------------------
# 条件路由函数
# ---------------------------------------------------------------------------

def route_after_intent(state: DevState) -> str:
    """三模式路由：chat → chat_agent，solve/diagnose → analyst"""
    mode = state.get("mode", "solve")
    if mode == "chat":
        return "chat_agent"
    return "analyst"


def route_after_analysis(state: DevState) -> str:
    mode = state.get("mode", "solve")
    if mode == "diagnose":
        return "qa"
    return "developer"


def route_after_developer(state: DevState) -> str:
    messages = state.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "developer_tools"
    return "qa"


def route_after_qa(state: DevState) -> str:
    messages = state.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "qa_tools"

    # 按 mode 选择出口：solve → tutor（完整题解），diagnose → chat_agent（反馈对话）
    mode = state.get("mode", "solve")
    exit_node = "chat_agent" if mode == "diagnose" else "tutor"

    feedback = state.get("execution_feedback", "")
    if not feedback:
        return exit_node

    retry_count = state.get("retry_count", 0)
    if retry_count >= 3:
        print(
            f"\n{'=' * 60}\n"
            f"\033[91m\U0001f6a8 熔断触发：已达最大重试次数 ({retry_count}/3)，"
            f"强制进入总结。\033[0m\n"
            f"{'=' * 60}\n"
        )
        return exit_node

    return "developer"


def route_after_chat_agent(state: DevState) -> str:
    """chat_agent 之后的工具调用检测。有 tool_calls → 执行工具 → 回传 chat_agent。"""
    messages = state.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "chat_agent_tools"
    return END


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------

def build_graph(checkpointer: Optional[AsyncPostgresSaver] = None) -> StateGraph:
    """构建 DevSwarm 算法推演平台完整执行图（类型提示已迁移为 AsyncPostgresSaver）"""
    workflow = StateGraph(DevState)

    workflow.add_node("intent_recognizer", intent_recognizer_node)
    workflow.add_node("analyst", analyst_node)
    workflow.add_node("developer", developer_node)
    workflow.add_node("qa", qa_node)
    workflow.add_node("tutor", tutor_node)
    workflow.add_node("chat_agent", chat_agent_node)

    workflow.add_node("developer_tools", ToolNode(_DEV_TOOLS))
    workflow.add_node("qa_tools", ToolNode(_QA_TOOLS))
    workflow.add_node("chat_agent_tools", ToolNode(_CHAT_TOOLS))

    workflow.set_entry_point("intent_recognizer")

    workflow.add_conditional_edges(
        "intent_recognizer",
        route_after_intent,
        {"analyst": "analyst", "chat_agent": "chat_agent"},
    )

    workflow.add_conditional_edges(
        "chat_agent",
        route_after_chat_agent,
        {"chat_agent_tools": "chat_agent_tools", END: END},
    )
    workflow.add_edge("chat_agent_tools", "chat_agent")

    workflow.add_conditional_edges(
        "analyst",
        route_after_analysis,
        {"developer": "developer", "qa": "qa"},
    )

    workflow.add_conditional_edges(
        "developer",
        route_after_developer,
        {"developer_tools": "developer_tools", "qa": "qa"},
    )
    workflow.add_edge("developer_tools", "developer")

    workflow.add_conditional_edges(
        "qa",
        route_after_qa,
        {"qa_tools": "qa_tools", "developer": "developer", "tutor": "tutor"},
    )
    workflow.add_edge("qa_tools", "qa")
    workflow.add_edge("tutor", END)

    return workflow.compile(checkpointer=checkpointer)


# ================================================================
# 全局单例编译
# ================================================================

checkpointer: Optional[AsyncPostgresSaver] = None
app = None


async def init_graph() -> None:
    """初始化 Postgres 检查点并编译图。必须在 FastAPI lifespan 中调用。"""
    global checkpointer, app

    checkpointer = AsyncPostgresSaver(pg_pool)

    # 强制初始化建表
    await checkpointer.setup()

    # 编译图并赋值给全局变量 app
    app = build_graph(checkpointer=checkpointer)
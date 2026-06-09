"""
DevSwarm 算法推演平台 —— Intent Recognizer 意图识别节点

作为图的入口第一站，用极轻量的 LLM 调用判断用户意图，
将对话路由到"做题流水线"或"答疑分支"。
"""

from core.utils.ha_utils import safe_llm_invoke
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from typing import Literal
from core.engine.state import DevState
from core.engine.llm_factory import llm_intent
from core.utils.memory_utils import trim_for_intent_recognizer
from schemas.knowledge_dict import AlgorithmTopic
from db.graph_reader import GraphReader

class IntentAndTopicExtraction(BaseModel):
    mode: Literal["solve", "diagnose", "chat"] = Field(
        description="用户意图三分类：求解新算法题 → 'solve'；提供了代码想调试 → 'diagnose'；提问/闲聊 → 'chat'"
    )
    current_topic: AlgorithmTopic = Field(
        description="用户当前讨论的核心算法。如果不在列表中，或是纯闲聊，必须输出 '未知或无关'"
    )

structured_llm = llm_intent.with_structured_output(IntentAndTopicExtraction)

# 轻量级意图分类提示词
_INTENT_PROMPT = SystemMessage(
    content=(
        "你是一个极其精准的意图与话题分类器。将用户消息分为三种模式：\n"
        "  - 'solve':    用户要求解新算法题（无代码，需从零编写）\n"
        "  - 'diagnose': 用户提供了代码，想要调试或诊断问题\n"
        "  - 'chat':     用户纯文字提问、闲聊、讨论概念\n\n"
        "同时提取用户当前讨论的【核心算法知识点】，从系统给定的 Enum 列表中选择最匹配的一项。\n"
        "如果用户没有提到具体的算法，或内容不在列表中，输出 `未知或无关`。"
    )
)


async def intent_recognizer_node(state: DevState) -> dict:
    """意图识别节点 —— 图入口第一站。

    读取 state["messages"] 中最后一条用户消息，
    用轻量 LLM 判断用户意图为 "task" 或 "chat"。

    Args:
        state: 当前 DevState。

    Returns:
        {"mode": "solve"|"diagnose"|"chat", "current_topic": ..., "user_memory_context": ...}
        不返回 messages，避免污染对话历史。
    """
    messages = state.get("messages", [])
    user_id = state.get("user_id")
    if not messages:
        return {"mode": "solve"}

    user_memory_context = ""
    if user_id:
        user_memory_context = await GraphReader.fetch_user_knowledge_profile(user_id)

    # 提取最后一条用户消息内容
    last_msg = trim_for_intent_recognizer(messages)
    user_input = getattr(last_msg, "content", "")
    if not user_input:
        return {"mode": "solve"}

    # 截断过长输入以控制 token 消耗
    truncated = user_input if len(user_input) <= 500 else user_input[:500]

    try:
        result: IntentAndTopicExtraction = safe_llm_invoke(
            structured_llm,
            [_INTENT_PROMPT, HumanMessage(content=truncated)]
        )

        extracted_topic = result.current_topic if result.current_topic != "未知或无关" else None

        # 兜底强制：如果用户在前端粘贴了代码，无论 LLM 怎么判，mode 必须是 diagnose
        mode = result.mode
        if state.get("user_code"):
            mode = "diagnose"

        return {
            "mode": mode,
            "current_topic": extracted_topic,
            "user_memory_context": user_memory_context,
        }

    except Exception as e:
        print(f"⚠️ [Intent Node] 结构化提取失败，已耗尽重试次数，触发降级: {e}")
        mode = "diagnose" if state.get("user_code") else "solve"
        return {
            "mode": mode,
            "current_topic": None,
            "user_memory_context": user_memory_context,
        }

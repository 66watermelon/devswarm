"""
DevSwarm 上下文记忆管理工具 (Context Window Trimmer)
为不同类型的 Agent 提供极其精准的视图投影（View Projection）。
"""
from typing import List, Set, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage


# ==============================================================================
# 内部辅助函数 (遵循 DRY 原则，消除重复的类型与属性检查)
# ==============================================================================

def _is_system_msg(msg: BaseMessage) -> bool:
    return isinstance(msg, SystemMessage)


def _is_human_or_user_msg(msg: BaseMessage) -> bool:
    """判定是否为用户发出的原始消息（兼容 HumanMessage 和指定了 name='user' 的消息）"""
    return isinstance(msg, HumanMessage) or getattr(msg, "name", "") == "user"


def _get_ai_role_name(msg: BaseMessage) -> str:
    """安全提取 AI 消息的 role name，如果不是 AI 消息则返回空"""
    if isinstance(msg, AIMessage):
        return getattr(msg, "name", "")
    return ""


# ==============================================================================
# 对外暴露的 API  
# ==============================================================================

def trim_for_intent_recognizer(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    【路由网关专属】：极简上下文，切断所有历史噪音。
    只保留当前最新的一条用户提问。
    """
    for msg in reversed(messages):
        if _is_human_or_user_msg(msg):
            return [msg]
    return messages[-1:] if messages else []


def trim_for_chat_agents(
        messages: List[BaseMessage],
        allowed_ai_roles: Set[str],
        keep_rounds: int = 3
) -> List[BaseMessage]:
    """
    【对话型 Agent 专属】 (Analyst, Tutor, ChatAgent)：滑动窗口过滤。
    保留系统指令、所有用户对话、以及白名单内 AI 的历史发言。
    """
    # 1. 绝对优先：分离出系统提示词 (保证 System Prompt 永不被截断)
    system_msgs = [msg for msg in messages if _is_system_msg(msg)]

    # 2. 收集有效的对话历史
    chat_history: List[BaseMessage] = []
    for msg in messages:
        if _is_system_msg(msg):
            continue  # 已经收集过，跳过

        if _is_human_or_user_msg(msg):
            chat_history.append(msg)
            continue

        role_name = _get_ai_role_name(msg)
        if role_name and role_name in allowed_ai_roles:
            chat_history.append(msg)

    # 3. 严格的滑动窗口截断 (一轮对话 = 1用户 + 1AI)
    max_history_len = (keep_rounds * 2) + 1
    recent_chat_history = chat_history[-max_history_len:] if len(chat_history) > max_history_len else chat_history

    # 4. 像三明治一样拼装：系统提示词 + 最近的历史对话
    return system_msgs + recent_chat_history


def trim_for_developer(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    【核心开发专属】：抗击“重试雪球效应”。
    极简模式：只保留 SystemMessage 和 最新的一次 QA 报错。
    (注意：用户需求已通过 state 组装进 SystemMessage 中，无需传递冗余的 User 消息)
    """
    filtered_messages: List[BaseMessage] = []
    latest_qa_msg: Optional[BaseMessage] = None

    # 1. 倒序查找，精准狙击最近的一次 QA 反馈
    for msg in reversed(messages):
        if _get_ai_role_name(msg) == "qa":
            latest_qa_msg = msg
            break

    # 2. 收集底层的系统指令
    for msg in messages:
        if _is_system_msg(msg):
            filtered_messages.append(msg)

    # 3. 追加错误情报
    if latest_qa_msg:
        filtered_messages.append(latest_qa_msg)

    return filtered_messages


def trim_for_qa(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    【判题沙箱专属】：绝对专注隔离区。
    只截取时间线上，最近一次 Developer 提交代码之后产生的所有消息（含工具调用）。
    彻底切断 Analyst 聊天记录对判题的干扰。
    """
    # 从后往前找，找到最后一个 Developer 出现的位置
    for i in range(len(messages) - 1, -1, -1):
        if _get_ai_role_name(messages[i]) == "developer":
            # 返回包含开发者消息及其之后的所有 tool calls 消息
            return messages[i:]

    # 兜底：如果是诊断模式 (没有 Developer)，则提取最后一条用户消息
    fallback_msgs = [m for m in messages if _is_human_or_user_msg(m)]
    return fallback_msgs[-1:] if fallback_msgs else messages[-1:]
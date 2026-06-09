"""
DevSwarm 消息清洗与内容提取工具

提供 LangGraph 节点输出解析、以及面向前端的消息清洗过滤。
"""

from typing import List

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


def extract_node_content(node_name: str, node_output: dict) -> str:
    """从 LangGraph 节点输出中提取适合前端展示的文本内容。

    按节点类型映射关键字段：
    - *_tools    → ToolMessage 结果摘要
    - analyst    → algorithm_strategy + edge_cases
    - developer  → 最后一条 AIMessage 的文本内容
    - qa         → execution_feedback
    - tutor      → final_explanation

    Args:
        node_name: 节点名称。
        node_output: 该节点的输出字典。

    Returns:
        格式化后的内容字符串。
    """
    # 工具节点：提取前 3 条 ToolMessage 摘要
    if node_name.endswith("_tools"):
        msgs = node_output.get("messages", [])
        parts = []
        for msg in msgs[:3]:
            c = str(getattr(msg, "content", ""))
            if c:
                parts.append(c[:300])
        return "\n".join(parts) if parts else "工具执行完成"

    # analyst：算法策略 + 边界用例
    if "algorithm_strategy" in node_output or "edge_cases" in node_output:
        parts = []
        s = node_output.get("algorithm_strategy", "")
        e = node_output.get("edge_cases", "")
        if s:
            parts.append(s)
        if e:
            parts.append("\n\n## 边界测试用例\n" + str(e))
        return "\n".join(parts)

    # developer / chat_agent / tutor：提取最后一条 AI 消息内容
    msgs = node_output.get("messages", [])
    for msg in reversed(msgs):
        c = getattr(msg, "content", "")
        if isinstance(c, str) and c.strip():
            return c

    # qa：执行反馈
    if "execution_feedback" in node_output:
        fb = node_output["execution_feedback"]
        return f"测试失败，报错如下：\n{fb}" if fb else "测试通过！代码正确运行。"

    # tutor：最终题解
    if "final_explanation" in node_output:
        return node_output["final_explanation"]

    return f"节点 [{node_name}] 执行完成"


def clean_messages(messages: list) -> List[dict]:
    """将 LangChain 消息对象清洗为前端可解析的 JSON 数组。

    过滤规则（按 msg.name 区分 Agent 身份）：
    - ToolMessage                          → 丢弃
    - AIMessage  name="developer" | "qa"   → 丢弃（内部执行日志）
    - AIMessage  name="analyst"            → {"role": "analyst", "content": "..."}
    - AIMessage  name="tutor"              → {"role": "tutor", "content": "..."}
    - HumanMessage                         → {"role": "user", "content": "..."}
    - 无 name 的 AIMessage                 → 丢弃（未知来源）

    Args:
        messages: LangGraph state 中的 messages 列表。

    Returns:
        清洗后的 dict 列表，可直接 JSON 序列化返回前端。
    """
    VISIBLE_NAMES = {"analyst", "tutor"}

    result = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            continue

        content = getattr(msg, "content", "")
        if isinstance(content, list):
            text_parts = [c.get("text", "") for c in content
                          if isinstance(c, dict) and c.get("type") == "text"]
            content = "\n".join(text_parts)
        if not isinstance(content, str) or not content.strip():
            continue

        if isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": content})
        elif isinstance(msg, AIMessage):
            name = getattr(msg, "name", "")
            if name in VISIBLE_NAMES:
                result.append({"role": name, "content": content})

    return result

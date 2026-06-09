"""
DevSwarm 算法推演平台 —— 执行节点包 (Nodes)

本包包含 LangGraph 图中各 Agent 节点的实现。

节点清单：
- intent_recognizer_node: Intent Recognizer —— 用户意图识别，路由决策入口
- analyst_node:          Analyst Agent    —— 算法复杂度分析 + 边界用例提取
- developer_node:        Developer Agent  —— 根据策略编写/修复 Python 题解代码
- qa_node:               QA Agent         —— 沙箱测试 + 严格判题
- tutor_node:            Tutor Agent      —— 最终 Markdown 题解输出
- chat_agent_node:       Chat Agent       —— 答疑解惑，导师风格陪聊
"""

from core.nodes.intent_recognizer_node import intent_recognizer_node
from core.nodes.analyst_node import analyst_node
from core.nodes.developer_node import developer_node
from core.nodes.qa_node import qa_node
from core.nodes.tutor_node import tutor_node
from core.nodes.chat_agent_node import chat_agent_node

__all__ = [
    "intent_recognizer_node",
    "analyst_node",
    "developer_node",
    "qa_node",
    "tutor_node",
    "chat_agent_node",
]

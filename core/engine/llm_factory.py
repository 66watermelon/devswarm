"""
DevSwarm 算法推演平台 —— LLM 连接池 (Connection Pool)

为所有 Agent 节点提供预实例化的 ChatOpenAI 单例。
每个 Agent 角色拥有独立的 LLM 实例，精确控制 temperature 和思考模式开关。

设计原则：
- 使用 pydantic.SecretStr 保护 API Key，防止日志/序列化泄露
- 模块级单例，避免每次调用重复创建连接
- 按角色拆分实例：Analyst/Tutor 保留思考模式，Developer/QA 关闭思考模式

思考模式策略：
- Analyst / Tutor：开启思考（算法分析和题解撰写需要深度推理）
- Developer / QA：强制关闭思考（Tool Calling 需要 reasoning_content 一致性）

提供的 LLM 实例：
- llm_analyst:    temp=0.3, 思考=ON  —— 算法复杂度分析 + 边界用例提取
- llm_developer:  temp=0.2, 思考=OFF —— 代码生成 + 文件工具调用
- llm_qa:         temp=0.1, 思考=OFF —— 沙箱测试 + 严苛判题
- llm_tutor:      temp=0.5, 思考=ON  —— 题解撰写 + Markdown 排版
"""

from typing import Any

from pydantic import SecretStr
from langchain_openai import ChatOpenAI

from core.config import settings

# ---------------------------------------------------------------------------
# 统一凭据
# ---------------------------------------------------------------------------
_api_key: SecretStr = SecretStr(settings.DEEPSEEK_API_KEY) if settings.DEEPSEEK_API_KEY else SecretStr("")
_base_url: str = settings.DEEPSEEK_BASE_URL

# ---------------------------------------------------------------------------
# LLM 实例池 —— 按 Agent 角色拆分
# ---------------------------------------------------------------------------

# 1. Analyst Agent（temp=0.3，思考模式：开启）
# 负责分析算法时间/空间复杂度，提取边缘测试用例。
# 需要深度推理能力来推导复杂度上界并发现隐藏的边界条件。
llm_analyst: ChatOpenAI = ChatOpenAI(
    model="deepseek-v4-pro",
    api_key=_api_key,
    base_url=_base_url,
    temperature=0.3,
    timeout=120,
    max_retries=0
)

# 2. Developer Agent（temp=0.2，思考模式：强制关闭）
# 需要频繁发起 Tool Call（读写文件），且处于 QA 打回→修复的多轮循环中。
# 思考模式会导致 reasoning_content 在消息序列化时丢失，触发 API 400 错误。
llm_developer: ChatOpenAI = ChatOpenAI(
    model="deepseek-v4-pro",
    api_key=_api_key,
    base_url=_base_url,
    temperature=0.2,
    timeout=120,
    model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
    max_retries=0
)

# 3. QA Agent（temp=0.1，思考模式：强制关闭）
# 需要发起 Tool Call（读代码、写测试、跑沙箱），且处于测试→打回→再测试的多轮循环中。
llm_qa: ChatOpenAI = ChatOpenAI(
    model="deepseek-v4-flash",
    api_key=_api_key,
    base_url=_base_url,
    temperature=0.1,
    timeout=120,
    model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
    max_retries=0
)

# 4. Tutor Agent（temp=0.5，思考模式：开启）
# 负责撰写最终题解，需要将算法的推导过程、代码实现和踩坑总结
# 融合成一篇生动易懂的 Markdown 教程。较高的 temperature 赋予文笔表现力。
llm_tutor: ChatOpenAI = ChatOpenAI(
    model="deepseek-v4-flash",
    api_key=_api_key,
    base_url=_base_url,
    temperature=0.5,
    timeout=120,
    max_retries=0,
    model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
)

# 5. Intent Recognizer（temp=0.0，思考模式：关闭）
# 轻量级意图分类器，仅输出 "task" 或 "chat"。
# 零温度确保分类结果稳定可复现。
llm_intent: ChatOpenAI = ChatOpenAI(
    model="deepseek-v4-flash",
    api_key=_api_key,
    base_url=_base_url,
    temperature=0.0,
    timeout=30,
    model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
    max_retries=0
)

# 6. Chat Agent（temp=0.5，思考模式：关闭）
# 专职陪聊/答疑节点，以算法导师口吻回复用户的各种提问。
llm_chat: ChatOpenAI = ChatOpenAI(
    model="deepseek-v4-flash",
    api_key=_api_key,
    base_url=_base_url,
    temperature=0.5,
    timeout=120,
    model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
    max_retries=0
)

# 7. Extractor Agent (temp=0.0, 思考模式: 强制关闭)
# 负责在后台将聊天记录榨取为 JSON 格式的图谱实体和关系。
# 必须彻底关闭幻觉和发散思维，保证 JSON 格式的绝对严谨。
llm_extractor: ChatOpenAI = ChatOpenAI(
    model="deepseek-v4-flash",
    api_key=_api_key,
    base_url=_base_url,
    temperature=0.0,
    timeout=60,
    max_retries=2
)

# ---------------------------------------------------------------------------
# 工具绑定辅助函数
# ---------------------------------------------------------------------------

def get_developer_llm_with_tools(tools: list[Any]) -> ChatOpenAI:
    """返回绑定了指定工具的 Developer LLM 实例。

    Args:
        tools: LangChain Tool 对象列表（通过 @tool 装饰器定义的函数）。

    Returns:
        已绑定工具的 ChatOpenAI 实例（思考模式已关闭）。
    """
    return llm_developer.bind_tools(tools)


def get_qa_llm_with_tools(tools: list[Any]) -> ChatOpenAI:
    """返回绑定了指定工具的 QA LLM 实例。"""
    return llm_qa.bind_tools(tools)


def get_chat_agent_llm_with_tools(tools: list[Any]) -> ChatOpenAI:
    """返回绑定了指定工具的 Chat Agent LLM 实例。

    当前绑定工具：recommend_next_topics（蜂群协同过滤推荐）。
    后续可扩展搜索、即时编译等工具。
    """
    return llm_chat.bind_tools(tools)

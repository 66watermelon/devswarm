"""
DevSwarm 算法推演平台 —— Tutor Agent 执行节点

Tutor（算法名师）是流水线的最后一个 Agent。
在所有测试通过后，汇总解题全过程，产出一篇生动易懂的 Markdown 题解。
"""

from langchain_core.messages import SystemMessage, AIMessage

from core.engine.state import DevState
from core.engine.llm_factory import llm_tutor
from core.prompts.tutor import TUTOR_SYSTEM_PROMPT
from core.tools import read_workspace_file
from core.utils.ha_utils import safe_llm_invoke
from core.utils.memory_utils import trim_for_chat_agents
from core.utils.graph_memory_injector import get_graph_memory_prompt

def _extract_text_content(response: AIMessage) -> str:
    """从 AIMessage 中安全提取纯文本内容。"""
    if isinstance(response.content, str):
        return response.content
    if isinstance(response.content, list):
        parts: list[str] = []
        for block in response.content:
            if isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(response.content)


async def tutor_node(state: DevState) -> dict:
    """Tutor Agent —— 最终 Markdown 题解输出。"""
    user_id = state.get("user_id")
    memory_block = await get_graph_memory_prompt(user_id)

    problem = state.get("problem_description", "")
    strategy = state.get("algorithm_strategy", "")
    edge = state.get("edge_cases", "")
    code = state.get("generated_code", "")

    if not code:
        try:
            code = read_workspace_file.invoke({"relative_path": "solution.py"})
        except Exception:
            code = "(code not found)"

    # 把业务数据移入 System Prompt，腾出 messages 用于多轮对话历史
    context = (
        f"{TUTOR_SYSTEM_PROMPT}\n\n"
        f"{memory_block}\n\n"
        "【系统指令】请根据以下信息，输出一篇完整的算法题解：\n\n"
        "## 题目\n" + problem + "\n\n"
        "## 算法策略\n" + strategy + "\n\n"
        "## 边界用例\n" + edge + "\n\n"
        "## 实现代码\n```python\n" + code + "\n```"
    )
    system_message = SystemMessage(content=context)

    # 过滤出聊天历史，完全屏蔽 Developer 废稿和 QA 的 traceback
    allowed_roles = {"analyst", "tutor", "chat_agent"}
    clean_history = trim_for_chat_agents(state.get("messages", []), allowed_roles, keep_rounds=3)

    messages = [system_message] + clean_history

    response = safe_llm_invoke(llm_tutor, messages)
    response.name = "tutor"

    explanation = _extract_text_content(response)

    return {"messages": [response], "final_explanation": explanation}
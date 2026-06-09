"""
DevSwarm 算法推演平台 —— QA Agent 执行节点

QA（判题官）是冷酷的裁判。不需要懂算法原理，
只负责生成测试脚本、调用沙箱执行、根据结果判定通过或失败。
"""

from langchain_core.messages import SystemMessage, AIMessage, ToolMessage

from core.engine.state import DevState
from core.engine.llm_factory import get_qa_llm_with_tools
from core.prompts.qa import QA_SYSTEM_PROMPT
from core.tools import read_workspace_file, write_workspace_file
from core.tools.sandbox_tool import run_sandbox_test
from core.utils.ha_utils import safe_llm_invoke
from core.utils.memory_utils import trim_for_qa

# QA 工具集：读代码、写测试、跑沙箱
_QA_TOOLS = [read_workspace_file, write_workspace_file, run_sandbox_test]

# 判定关键字
_PASS_MARKER = "【测试通过】"
_FAIL_MARKER = "【测试失败】"


def _build_qa_system_prompt(state: DevState) -> str:
    """根据当前状态动态组装 QA 的系统提示词。

    在基础 QA_SYSTEM_PROMPT 之上追加：
    1. 题目描述（了解需要在哪个文件找代码）
    2. 边界测试用例（Analyst 产出的 assert 语句）

    Args:
        state: 当前 DevState。

    Returns:
        组装完成的系统提示词字符串。
    """
    parts = [QA_SYSTEM_PROMPT]

    problem = state.get("problem_description", "")
    if problem:
        parts.append(
            f"\n{'─' * 60}\n📝 待验证的算法题目\n{'─' * 60}\n{problem}"
        )

    edge = state.get("edge_cases", "")
    if edge:
        parts.append(
            f"\n{'─' * 60}\n🔍 Analyst 指定的边界测试用例\n"
            f"请确保以下 assert 全部通过\n{'─' * 60}\n{edge}"
        )

    mode = state.get("mode", "solve")

    # 诊断模式：优先测 developer 修复后的代码，否则测用户原始代码
    if mode == "diagnose":
        code_to_test = state.get("generated_code", "") or state.get("user_code", "")
        source_label = "Developer 已修复，请验证修复后的代码" if state.get("generated_code") else "用户提供的待诊断代码"
        if code_to_test:
            parts.append(
                f"\n{'─' * 60}\n🔧 诊断模式：{source_label}\n"
                f"请先将此代码写入 workspace/solution.py，然后运行测试\n"
                f"{'─' * 60}\n```python\n{code_to_test}\n```"
            )
            parts.append(
                "\n【诊断模式判题侧重】优先关注代码中的逻辑错误和边界漏洞，"
                "而非性能或风格问题。"
            )
        else:
            parts.append(
                "\n⚠️ 诊断模式已触发但未找到待测代码（user_code 和 generated_code 均为空）。"
                "将读取 workspace/solution.py 中的已有文件进行测试。"
            )

    return "\n".join(parts)


def _extract_feedback(content: str) -> str:
    """从 LLM 回复中提取 QA 的分析内容（去除判定标记）。

    Args:
        content: LLM 回复的完整文本。

    Returns:
        去除标记后的纯分析文本。
    """
    text = content.replace(_PASS_MARKER, "").replace(_FAIL_MARKER, "").strip()
    return text if text else content.strip()


def qa_node(state: DevState) -> dict:
    """QA Agent 执行节点 —— 沙箱测试与判题。

    执行流程：
    1. 读取 workspace/solution.py 中的代码。
    2. 编写 test_solution.py 测试脚本。
    3. 调用 run_sandbox_test 执行测试。
    4. 根据结果输出【测试通过】或【测试失败】。

    Args:
        state: 当前 DevState。

    Returns:
        dict: 包含 messages、execution_feedback、retry_count 的更新字典。
    """
    # ---- 1. 动态组装系统提示词 ----
    system_content = _build_qa_system_prompt(state)
    system_message = SystemMessage(content=system_content)

    # ---- 2. 获取绑定工具的 LLM（思考模式已关闭） ----
    llm = get_qa_llm_with_tools(_QA_TOOLS)

    # ---- 3. 构造专注的消息并调用 ----
    clean_history = trim_for_qa(state.get("messages", []))
    messages = [system_message] + clean_history

    response = safe_llm_invoke(llm, messages)
    response.name = "qa"

    # ---- 4. ToolCall 检测 ----
    if isinstance(response, AIMessage) and response.tool_calls:
        return {"messages": [response]}

    # ---- 5. 提取响应文本 ----
    content: str = ""
    if isinstance(response.content, str):
        content = response.content
    elif isinstance(response.content, list):
        parts_list = []
        for block in response.content:
            if isinstance(block, dict) and "text" in block:
                parts_list.append(block["text"])
            elif isinstance(block, str):
                parts_list.append(block)
        content = "".join(parts_list)

    # ---- 6. 解析判定结果 ----
    result_update: dict = {"messages": [response]}

    if _PASS_MARKER in content:
        result_update["execution_feedback"] = ""
        result_update["retry_count"] = 0

    elif _FAIL_MARKER in content:
        feedback = _extract_feedback(content)
        current_retry = state.get("retry_count", 0)
        result_update["execution_feedback"] = feedback
        result_update["retry_count"] = current_retry + 1

    # ---- 7. 诊断模式首轮：提取沙箱原始输出，供 chat_agent 诊断出口使用 ----
    # 仅在 generated_code 为空时写入（即 user_code 的首次测试结果，非 developer 修复后的重测）
    if state.get("mode") == "diagnose" and not state.get("generated_code"):
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, ToolMessage) and getattr(msg, "name", "") == "run_sandbox_test":
                result_update["diagnose_report"] = str(msg.content)
                break

    return result_update
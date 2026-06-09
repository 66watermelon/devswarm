"""
DevSwarm 算法推演平台 —— Developer Agent 执行节点

Developer（算法工程师）根据 Analyst 的算法策略和边界用例，
编写/修复规范的 Python 题解代码。
"""
import re
from langchain_core.messages import SystemMessage

from core.engine.state import DevState
from core.engine.llm_factory import get_developer_llm_with_tools
from core.prompts.developer import DEVELOPER_SYSTEM_PROMPT
from core.utils.ha_utils import safe_llm_invoke
from core.utils.memory_utils import trim_for_developer
from core.tools import (
    read_workspace_file,
    write_workspace_file,
    list_workspace_files,
)

_DEV_TOOLS = [read_workspace_file, write_workspace_file, list_workspace_files]


def _build_developer_system_prompt(state: DevState) -> str:
    """根据当前状态动态组装 Developer 的系统提示词。"""
    parts = [DEVELOPER_SYSTEM_PROMPT]

    # ---- 模式感知 ----
    mode = state.get("mode", "solve")
    user_code = state.get("user_code", "")
    retry = state.get("retry_count", 0)

    if mode == "diagnose":
        parts.append(
            "\n" + "=" * 60 + "\n【诊断模式 —— 修复已有代码】\n" + "=" * 60 + "\n"
            "你的任务是修复代码中的问题，而不是从零重写。\n"
            "保留原有的代码结构和思路，只修改有问题的地方。\n"
        )
        if retry > 0:
            prev_code = state.get("generated_code", "")
            if prev_code:
                parts.append("## 你上一次提交的代码\n```python\n" + prev_code + "\n```")
        else:
            if user_code:
                parts.append("## 用户的原始代码\n```python\n" + user_code + "\n```")
    else:
        parts.append(
            "\n" + "=" * 60 + "\n【求解模式 —— 从零编写代码】\n" + "=" * 60
        )

    # ---- 题目 ----
    problem = state.get("problem_description", "")
    if problem:
        parts.append("\n" + "-" * 60 + "\n算法题目\n" + "-" * 60 + "\n" + problem)

    # ---- Analyst 策略 ----
    strategy = state.get("algorithm_strategy", "")
    if strategy:
        parts.append("\n" + "-" * 60 + "\nAnalyst 分析\n" + "-" * 60 + "\n" + strategy)

    # ---- 边界用例 ----
    edge = state.get("edge_cases", "")
    if edge:
        parts.append("\n" + "-" * 60 + "\n边界测试用例\n" + "-" * 60 + "\n" + edge)

    # ---- QA 打回反馈 ----
    feedback = state.get("execution_feedback", "")
    if feedback and retry > 0:
        parts.append(
            "\n" + "=" * 60 + "\n"
            "第 " + str(retry) + " 次判题打回\n"
            + "=" * 60 + "\n"
            "上一次提交的代码未通过测试，请修复：\n\n" + feedback
        )

    return "\n".join(parts)


def developer_node(state: DevState) -> dict:
    """Developer Agent —— 算法代码产出与修复。"""
    system_content = _build_developer_system_prompt(state)
    system_message = SystemMessage(content=system_content)
    llm = get_developer_llm_with_tools(_DEV_TOOLS)

    # 极限模式，抗击重试雪球效应
    # Developer 眼里只剩下：系统指令（题目+策略） + 原始需求 + 最新的一次 QA 报错
    clean_history = trim_for_developer(state.get("messages", []))
    messages = [system_message] + clean_history

    # 1. 调用 LLM
    response = safe_llm_invoke(llm, messages)
    # 打上身份标签，防止前端混乱
    response.name = "developer"

    # 2. 从回复内容中提取代码块
    extracted_code = state.get("generated_code", "")  # 默认继承上一次的代码
    if response.content:
        # 使用 \x60{3} 代替硬编码的反引号，彻底杜绝 Markdown 渲染截断问题
        # \s* 增强了包容性，允许大模型在代码块首尾出现不规则的空格或无换行
        pattern = r"\x60{3}(?:python)?\s*(.*?)\s*\x60{3}"

        match = re.search(pattern, response.content, re.DOTALL)
        if match:
            extracted_code = match.group(1).strip()
        else:
            # 兼容处理：兜底匹配任何没有声明语言的代码块
            fallback_pattern = r"\x60{3}\s*(.*?)\s*\x60{3}"
            fallback_match = re.search(fallback_pattern, response.content, re.DOTALL)
            if fallback_match:
                extracted_code = fallback_match.group(1).strip()

    # 3. 把提取出来的代码写入 generated_code 状态中
    return {
        "messages": [response],
        "generated_code": extracted_code
    }
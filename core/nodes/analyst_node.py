"""
DevSwarm 算法推演平台 —— Analyst Agent 执行节点

Analyst（算法分析师）负责深度分析算法题目的核心难点，
推导时间/空间复杂度，并提取极限边界测试用例。
Analyst 绝对不写代码，只产出算法策略文档。
"""

from langchain_core.messages import SystemMessage, AIMessage

from core.engine.state import DevState
from core.engine.llm_factory import llm_analyst
from core.prompts.analyst import ANALYST_SYSTEM_PROMPT
from core.utils.ha_utils import safe_llm_invoke
from core.utils.memory_utils import trim_for_chat_agents
from db.graph_reader import GraphReader

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


def _parse_analyst_output(content: str) -> dict[str, str]:
    algorithm_strategy = content.strip()
    # 熔断保护：如果 Analyst 填入了“暂缓推演”标志，直接清空测试用例
    if "前置基础严重不足，暂缓推演" in algorithm_strategy:
        return {"algorithm_strategy": algorithm_strategy, "edge_cases": ""}

    edge_cases = ""
    in_code_block = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block and (stripped.startswith("assert ") or stripped.startswith("#")):
            edge_cases += stripped + "\n"
    if not edge_cases:
        edge_cases = algorithm_strategy
    return {"algorithm_strategy": algorithm_strategy, "edge_cases": edge_cases.strip()}


async def analyst_node(state: DevState) -> dict:
    """Analyst Agent —— 算法分析与边界用例提取。"""
    problem = state.get("problem_description", "").strip()
    user_id = state.get("user_id")
    current_topic = state.get("current_topic")
    if not problem:
        raise ValueError("problem_description is empty")

    prereq_warning = ""
    if current_topic:
        # 1. 多跳雷达，获取拓扑图数据
        missing_data = await GraphReader.check_prerequisites(user_id, current_topic)
        missing_concepts = missing_data.get("missing_concepts", [])
        dependency_edges = missing_data.get("dependency_edges", [])

        if missing_concepts:
            # 2. 动态拼装清晰的依赖链条文本供 LLM 推理
            if dependency_edges:
                edges_text = "\n".join(
                    [f"   - 【{edge['from']}】 ➔ 必须先于 ➔ 【{edge['to']}】" for edge in dependency_edges])
            else:
                edges_text = "   - 暂无内部嵌套依赖（缺失节点相互独立）"

            # 3. 升级分析师的提示词：侧重于学习路径的严谨架构
            prereq_warning = (
                f"\n\n🚨 【图谱雷达高级拦截指令 (CRITICAL)】\n"
                f"警告：该用户试图挑战【{current_topic}】，但底层知识图谱显示存在深层基础断层！\n"
                f"▶ 1. 全量缺失知识点：{', '.join([f'【{c}】' for c in missing_concepts])}\n"
                f"▶ 2. 缺失知识点内部的拓扑关系链：\n{edges_text}\n\n"
                f"【🔥 你的核心任务变更】：\n"
                f"请立刻放弃为当前目标题目生成任何代码推演策略！你现在的身份变更为【首席学习路径架构师】。请在 `algorithm_strategy` 中输出一份极其严谨的【渐进式复习打卡路线大纲】。要求：\n"
                f"1. 仔细阅读拓扑关系链，找出【入度为 0 的最根源断层】（即最底层的基石知识点，例如用户连 Level 1 都不懂，绝不能让他去学 Level 2）。\n"
                f"2. 明确指出用户当前产生挫败感的根本死穴所在，并在大纲中强制后续导师必须从‘最根源断层’开始带用户逐级补课，直到串联回当前话题！"
            )

    # 1. 动态把题目注入到 SystemPrompt 中，保证作为绝对约束指令
    user_memory_context = state.get("user_memory_context", "")       
    if user_memory_context.strip():
        memory_block = f"【用户知识档案】\n{user_memory_context}"
    else:
        memory_block = "【用户知识档案】\n暂无记录（按零基础分析）"

    system_content = f"{ANALYST_SYSTEM_PROMPT}\n\n{memory_block}\n\n【当前需分析题目】\n{problem}"
    if prereq_warning:
        system_content += prereq_warning

    # 按 mode 追块：diagnose 下输出代码审查指引，而非完整算法策略
    mode = state.get("mode", "solve")
    if mode == "diagnose":
        system_content += (
            "\n\n【诊断模式特别指令】\n"
            "用户已经提供了自己的代码。你的任务：\n"
            "1. 根据【用户知识档案】，输出一份【代码审查指引】到 algorithm_strategy 字段，\n"
            "   指明修复代码时可以使用哪些知识点、应该避开用户的薄弱点、保持什么编码风格。\n"
            "   不要写完整的算法推导或复杂度分析。\n"
            "2. 提取针对用户代码的边界测试用例（assert 语句）到 edge_cases 字段，\n"
            "   覆盖用户代码可能遗漏的边界条件。"
        )

    system_message = SystemMessage(content=system_content)

    # 2. 调用记忆截断过滤器（保持原有逻辑不动）
    allowed_roles = {"analyst", "tutor", "chat_agent"}
    clean_history = trim_for_chat_agents(
        state.get("messages", []),
        allowed_ai_roles=allowed_roles,
        keep_rounds=3
    )

    # 3. 组装最终带记忆的消息流
    messages = [system_message] + clean_history

    response = safe_llm_invoke(llm_analyst, messages)
    response.name = "analyst"

    content = _extract_text_content(response)
    parsed = _parse_analyst_output(content)

    return {
        "messages": [response],
        "algorithm_strategy": parsed["algorithm_strategy"],
        "edge_cases": parsed["edge_cases"],
    }


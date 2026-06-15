"""
DevSwarm 算法推演平台 —— Chat Agent 答疑解惑节点

当用户意图被识别为 "chat" 时，由此节点接棒。
以算法导师的口吻解答各种提问，复用 tutor 身份以便前端正常渲染。
"""

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from core.engine.state import DevState
from core.engine.llm_factory import get_chat_agent_llm_with_tools
from core.prompts.chat_agent import CHAT_AGENT_SYSTEM_PROMPT
from core.utils.ha_utils import safe_llm_invoke
from core.utils.memory_utils import trim_for_chat_agents
from core.utils.graph_memory_injector import get_graph_memory_prompt
from core.tools.recommendation_tool import recommend_topics
from db.graph_reader import GraphReader

def _build_context(state: DevState) -> str:
    """从状态中构建上下文摘要，帮助 Chat Agent 理解当前场景。"""
    parts = []

    current_code = state.get("generated_code", "") or state.get("user_code", "")
    if current_code:
        # 使用 \x60 绕过系统的 Markdown 截断 Bug
        parts.append(
            "## 当前工作区代码\n"
            "\x60\x60\x60python\n" + current_code[:2000] + "\n\x60\x60\x60"
        )

    problem = state.get("problem_description", "")
    if problem:
        parts.append("## 正在解决的题目\n" + problem)

    strategy = state.get("algorithm_strategy", "")
    if strategy:
        parts.append("## 已有的算法分析\n" + strategy[:1000])

    feedback = state.get("execution_feedback", "")
    if feedback:
        parts.append("## QA 分析\n" + feedback[:1000])

    sandbox = state.get("diagnose_report", "")
    if sandbox:
        parts.append("## 沙箱测试原始输出\n" + sandbox[:1500])

    return "\n\n".join(parts) if parts else "（暂无上下文，这是一个全新的对话）"


async def chat_agent_node(state: DevState) -> dict:
    """Chat Agent —— 专职答疑解惑（已完美接入多跳图谱雷达）。"""
    user_id = state.get("user_id")
    current_topic = state.get("current_topic")
    memory_block = await get_graph_memory_prompt(user_id)

    prereq_warning = ""
    if current_topic:
        # 1. 调用多跳雷达，获取拓扑图数据
        missing_data = await GraphReader.check_prerequisites(user_id, current_topic)
        missing_concepts = missing_data.get("missing_concepts", [])
        dependency_edges = missing_data.get("dependency_edges", [])

        if missing_concepts:
            if dependency_edges:
                edges_text = "\n".join(
                    [f"   - 【{edge['from']}】 ➔ 必须先于 ➔ 【{edge['to']}】" for edge in dependency_edges])
            else:
                edges_text = "   - 暂无内部嵌套依赖（缺失知识点相互独立）"

            prereq_warning = (
                f"\n\n🚨 【图谱雷达拦截与教学重定向 (CRITICAL)】\n"
                f"当前会话关联的话题为【{current_topic}】，但系统检测到用户缺失前置依赖：\n"
                f"▶ 缺失节点：{', '.join([f'【{c}】' for c in missing_concepts])}\n"
                f"▶ 依赖线索：\n{edges_text}\n\n"
                f"【🔥 你的导师行动指南】：\n"
                f"1. 【严禁直答】：绝对不要直接回答用户关于高级算法【{current_topic}】的核心提问！\n"
                f"2. 【围魏救赵】：请展现出极高的教学素养。通过阅读依赖线索，找出最底层的最根源概念。以一种长辈和温和导师的口吻，委婉地告诉对方：‘在研究这个问题前，我们可能需要先理清一个更好玩的基础概念……’。\n"
                f"3. 【交互式测验】：在本次回复中，主动抛出一个针对【最底层缺失概念】的极简小提问（如概念连连看、核心伪代码猜谜等），测试他是否真的不懂，逐步引导他夯实地基，阻止他的越级低效学习。"
            )

    context = _build_context(state)
    system_content = f"{CHAT_AGENT_SYSTEM_PROMPT}\n\n{memory_block}{prereq_warning}\n\n【系统内部状态】\n{context}"

    # diagnose 模式出口：追加角色指令
    mode = state.get("mode", "solve")
    if mode == "diagnose":
        feedback = state.get("execution_feedback", "")
        if feedback:
            system_content += (
                "\n\n【诊断模式出口 —— 测试失败反馈】\n"
                "用户提供了代码，QA 沙箱已跑完测试但失败了。\n"
                "你的任务：用导师口吻告诉用户代码的问题在哪，结合上方【QA 分析】和【沙箱测试原始输出】指出具体错误，"
                "给出修复建议（但不是直接重写）。保持鼓励和耐心。"
            )
        else:
            system_content += (
                "\n\n【诊断模式出口 —— 测试通过反馈】\n"
                "用户提供的代码已通过所有测试。\n"
                "你的任务：恭喜用户，结合上方【沙箱测试原始输出】展示测试结果，"
                "简要总结代码的亮点，分析时间/空间复杂度。"
                "如果还有优化空间可以温和提示。"
            )

    system_message = SystemMessage(content=system_content)

    # 2. 调用记忆截断过滤器（保持原有逻辑不动）
    allowed_roles = {"analyst", "tutor", "chat_agent"}
    clean_history = trim_for_chat_agents(
        state.get("messages", []),
        allowed_ai_roles=allowed_roles,
        keep_rounds=3
    )

    # 3. 组装最终发给大模型的消息（绑定蜂群推荐 tool）
    messages = [system_message] + clean_history

    llm = get_chat_agent_llm_with_tools([recommend_topics])
    response = safe_llm_invoke(llm, messages)
    response.name = "chat_agent"

    return {"messages": [response]}
"""
DevSwarm 算法推演平台 —— 全局状态字典 (State)

在 LangGraph 中，图的每一个节点（Agent）都会接收这个 State，
修改其中的某些字段，然后将新的 State 传递给下一个节点。
"""

from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage
from typing import Optional

class DevState(TypedDict):
    """算法推演与学习平台的全局状态。

    字段分为四组：输入层、分析层、执行层、输出层。
    每层由不同的 Agent 负责读写，形成清晰的单向数据流。
    """

    # ==========================================
    # 1. 核心对话流（LangGraph 内建）
    # ==========================================
    messages: Annotated[list[AnyMessage], add_messages]
    """所有 Agent 之间的对话记录，由 add_messages reducer 自动追加。"""

    # ==========================================
    # 2. 输入层 —— 用户提供
    # ==========================================
    problem_description: str
    """算法题目描述，用户输入的自然语言。例如："实现二分查找，返回目标值的索引"。"""

    user_code: str
    """诊断模式专用：用户已有的、可能存在 Bug 的代码。
    求解模式下此字段为空字符串。"""

    # ==========================================
    # 3. 分析层 —— Analyst 产出
    # ==========================================
    algorithm_strategy: str
    """Analyst 产出的算法思路，包含时间/空间复杂度分析和关键步骤拆解。"""

    edge_cases: str
    """Analyst 提取的边缘测试用例列表，格式为 Python 可执行的 assert 语句。
    例如：
    assert binary_search([1,2,3], 2) == 1
    assert binary_search([], 5) == -1
    """

    # ==========================================
    # 4. 执行层 —— Developer 产出、QA 反馈
    # ==========================================
    generated_code: str
    """Developer 生成/修复后的 Python 题解代码（含注释）。"""

    execution_feedback: str
    """QA 沙箱执行后的反馈。
    - 成功时为空字符串
    - 失败时包含完整的沙箱报告（退出码 + stdout + stderr）
    """

    # ==========================================
    # 5. 输出层 —— Tutor 产出
    # ==========================================
    final_explanation: str
    """Tutor 产出的最终 Markdown 题解，包含思路、代码、踩坑总结。"""

    # ==========================================
    # 6. 控制层
    # ==========================================
    retry_count: int
    """QA 打回 Developer 的重试计数器，默认 0，上限 3。"""

    mode: str
    """图执行模式（三值，由 intent_recognizer 节点产出）：
    - "solve":    求解模式（从零推导算法 → 写代码 → 测试 → 讲解）
    - "diagnose": 诊断模式（用户提供代码 → QA 测试 → 反馈对话）
    - "chat":     聊天模式（纯文字提问 → chat_agent 答疑）
    """

    # ==========================================
    # 7. 执行过程追踪
    # ==========================================
    retry_count: int
    """QA 打回 Developer 的重试计数器，默认 0，上限 3。"""

    user_id: int

    current_topic: Optional[str]

    user_memory_context: str

    diagnose_report: str
    """诊断模式下 QA 对 user_code 的沙箱测试原始输出。
    由 QA 节点在 diagnose 模式时从 ToolMessage 中提取写入，
    供 chat_agent 在 diagnose 出口向用户展示详细的测试结果。"""

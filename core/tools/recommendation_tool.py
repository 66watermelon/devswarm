"""
DevSwarm 蜂群推荐工具

将 Neo4j 协同过滤推荐封装为 LangChain Tool，
供 chat_agent 在用户询问"接下来学什么"时主动调用。
"""

from langchain_core.tools import tool

from db.graph_reader import GraphReader


@tool
async def recommend_topics(user_id: int) -> str:
    """查询与当前用户水平相近的其他用户最近在学什么算法。

    返回最多 3 个推荐知识点，按蜂群热度降序排列。
    每个推荐都满足：用户已掌握该知识点的全部前置依赖。

    适用场景：用户问"推荐一道题""接下来学什么""我该补哪个知识点"时调用。
    其他类型的问题（时间复杂度分析、代码调试、概念解释）不需要调用此工具。

    Args:
        user_id: 当前用户 ID。
    """
    recs = await GraphReader.get_swarm_recommendations(user_id)
    if not recs:
        return "暂无推荐。用户可能需要先掌握更多基础知识，或系统尚未积累足够的同类用户数据。"

    lines = ["## 蜂群推荐 —— 和你水平相近的用户最近在学："]
    for i, r in enumerate(recs, 1):
        lines.append(f"{i}. **{r['concept']}** —— {r['peer_count']} 位同类用户近期掌握")
    return "\n".join(lines)

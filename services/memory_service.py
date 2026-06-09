"""
DevSwarm GraphRAG 记忆吸收服务

负责在后台静默执行认知图谱的记忆提取与 Neo4j 写入。
不阻塞主流程，异常自消化。
"""

import logging

from langchain_core.messages import HumanMessage, AIMessage

import main_graph
from core.constants import EXTRACTABLE_ROLES
from core.engine.memory_extractor import MemoryExtractorService
from db.graph_writer import GraphWriter

logger = logging.getLogger(__name__)


async def absorb_memory_pipeline(user_id: int, thread_id: str) -> None:
    """后台记忆吸收专线：从 Checkpoint 还原现场 → LLM 提取认知 → Neo4j 写入。

    在推演 Worker 完成并发送 [EOF] 后调用，此时 Redis 锁仍保持，
    用户无法发起新请求，确保数据一致性。

    Args:
        user_id: 用户 ID（int，与 Neo4j User {id} 类型一致）。
        thread_id: 会话 UUID。
    """
    try:
        logger.info(f"🧠 [MemoryPipeline] 开始处理用户 {user_id} 的后台认知吸收...")

        # 1. 还原现场：从 Checkpoint 拿到最新的状态字典
        config = {"configurable": {"thread_id": thread_id}}
        state = await main_graph.app.aget_state(config)

        if not state or not state.values or "messages" not in state.values:
            return

        current_topic = state.values.get("current_topic")
        all_messages = state.values["messages"]

        # 2. 净化剧本：只保留 User 和前台 Agent 的对话，过滤内部噪音防幻觉
        front_stage_msgs = [
            msg for msg in all_messages
            if isinstance(msg, HumanMessage) or
               (isinstance(msg, AIMessage) and getattr(msg, "name", "") in EXTRACTABLE_ROLES)
        ]

        if not front_stage_msgs:
            return

        # 3. 提取 → 4. 入库
        extractor = MemoryExtractorService()
        extracted_memory = await extractor.extract_from_history(front_stage_msgs)
        await GraphWriter.save_memory(
            user_id=user_id,
            memory=extracted_memory,
            current_topic=current_topic,
        )

        logger.info(f"🧠 [MemoryPipeline] 用户 {user_id} 的认知图谱生长完毕！")

    except Exception as e:
        logger.error(f"❌ [MemoryPipeline] 记忆吸收发生异常: {e}", exc_info=True)

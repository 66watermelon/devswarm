import logging
from db.neo4j_client import AsyncNeo4jClient
from schemas.graph_memory import ExtractedGraphMemory, MasteryStatus
from schemas.algorithm_data import ALGORITHM_DATA

logger = logging.getLogger(__name__)


VALID_CONCEPTS = {node["id"] for node in ALGORITHM_DATA["nodes"]}

class GraphWriter:
    WEIGHT_DELTA_MAP = {
        MasteryStatus.FAILED: 2,
        MasteryStatus.PROGRESSING: 1,
        MasteryStatus.MASTERED: -2
    }

    @staticmethod
    async def save_memory(user_id: int, memory: ExtractedGraphMemory, current_topic: str = None):
        """
        供外部调用的主入口函数。
        利用意图识别的前置确切结果，强行校准大模型事后提取的误差。
        """
        if not memory.concepts and not memory.assessments:
            logger.info(f"[GraphWriter] 用户 {user_id} 本轮无有效认知数据可提取。")
            return

        driver = AsyncNeo4jClient.get_driver()

        # ---------------------------------------------------------------------
        # 强制约束大模型的幻觉
        # ---------------------------------------------------------------------
        assessments_data = []
        for a in memory.assessments:
            a_dict = a.model_dump()
            extracted_name = a_dict['concept_name']

            # 如果系统当前有明确讨论的 current_topic，直接覆盖！(优先级最高)
            if current_topic and current_topic != "未知或无关":
                a_dict['concept_name'] = current_topic

            # 如果没有 current_topic (比如闲聊)，但大模型非要提取一个字典外的野名字，直接丢弃该条记录
            elif extracted_name not in VALID_CONCEPTS:
                logger.warning(f"[GraphWriter] 拦截非法节点: {extracted_name}，不在系统白名单中！")
                continue

            a_dict['weight_delta'] = GraphWriter.WEIGHT_DELTA_MAP.get(a.status, 0)
            a_dict['status_value'] = a.status.value if hasattr(a.status, 'value') else a.status
            assessments_data.append(a_dict)

        concepts_data = [c.model_dump() for c in memory.concepts]
        frustration = memory.user_state.frustration_level
        bad_smells = memory.user_state.bad_code_smells

        async with driver.session(database="neo4j") as session:
            try:
                await session.execute_write(
                    GraphWriter._cypher_transaction,
                    user_id,
                    concepts_data,
                    assessments_data,
                    frustration,
                    bad_smells
                )
                logger.info(f"✅ [GraphWriter] 用户 {user_id} 的认知图谱更新成功！")
            except Exception as e:
                logger.error(f"❌ [GraphWriter] 图谱写入失败: {e}")

    @staticmethod
    async def _cypher_transaction(tx, user_id, concepts, assessments, frustration, bad_smells):
        """
        真正的 Cypher 事务层，被上面的 execute_write 内部调用。
        """
        # ==========================================
        # 步骤 1：更新或创建“用户画像节点”
        # ==========================================
        await tx.run("""
            MERGE (u:User {id: $user_id})
            SET u.frustration_level = $frustration,
                u.bad_code_smells = $bad_smells,
                u.last_active = datetime()
        """, user_id=user_id, frustration=frustration, bad_smells=bad_smells)

        # ==========================================
        # 步骤 2：批量合并“知识点节点”
        # ==========================================
        if concepts:  
            await tx.run("""
                UNWIND $concepts AS concept
                MERGE (c:Concept {name: concept.name})
                SET c.category = concept.category
            """, concepts=concepts)

        # ==========================================
        # 步骤 3：构建认知连线
        # ==========================================
        if assessments:
            await tx.run("""
                MATCH (u:User {id: $user_id})
                UNWIND $assessments AS ax

                // 防御大模型幻觉，静默创建可能遗漏的知识点
                MERGE (c:Concept {name: ax.concept_name})

                // 在人和知识点之间，建立一根名为 UNDERSTANDS 的连线
                MERGE (u)-[r:UNDERSTANDS]->(c)

                // ==========================================
                // 【重构核心】：彻底解耦的数学计算
                // 直接使用 Python 传进来的 ax.weight_delta 进行加减计算
                // ==========================================
                WITH r, ax, coalesce(r.error_weight, 0) + ax.weight_delta AS temp_weight

                // 把算好的权重存回这根连线上，并锁定在 0 到 10 的区间内
                SET r.error_weight = CASE 
                        WHEN temp_weight < 0 THEN 0 
                        WHEN temp_weight > 10 THEN 10 
                        ELSE temp_weight 
                    END,
                    r.status = ax.status_value,         // 使用传入的纯字符串
                    r.error_pattern = ax.error_pattern,
                    r.context_summary = ax.context_summary, 
                    r.last_updated = datetime()         
            """, user_id=user_id, assessments=assessments)
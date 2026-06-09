from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Literal, Optional
import logging

from db.neo4j_client import AsyncNeo4jClient
from schemas.knowledge_dict import AlgorithmTopic

logger = logging.getLogger(__name__)
router = APIRouter()


# ==========================================
# 1. 数据契约定义 (Data Schemas)
# ==========================================

class SkillUpdateItem(BaseModel):
    concept: AlgorithmTopic
    state: Literal["mastered", "progressing", "unlearned"]  # 3 态模型


class MasteryUpdateRequest(BaseModel):
    user_id: int
    skill_updates: List[SkillUpdateItem]


# ==========================================
# 接口 1: 获取用户全景画像与技能树 (GET)
# ==========================================
@router.get("/profile/{user_id}")
async def get_user_profile(user_id: int):
    """查询用户的全量能力图谱、性格画像与错题本"""
    driver = AsyncNeo4jClient.get_driver()
    async with driver.session(database="neo4j") as session:
        try:
            # 第一步：查询全量知识图谱的基建 (所有的点和所有的线)
            # 使用 WITH 分隔查询，避免笛卡尔积
            graph_query = """
                            MATCH (c:Concept)
                            WITH c ORDER BY c.level ASC, c.category ASC, c.name ASC
                            WITH collect({name: c.name, category: c.category, level: c.level}) AS nodes
                            OPTIONAL MATCH (c1:Concept)-[:PREREQUISITE_FOR]->(c2:Concept)
                            RETURN nodes, collect(DISTINCT {source: c1.name, target: c2.name}) AS dependencies
                        """
            graph_result = await session.run(graph_query)
            graph_record = await graph_result.single()

            nodes = graph_record["nodes"] if graph_record else []
            # 洗掉 target 为 None 的空连线
            dependencies = [d for d in graph_record["dependencies"] if d.get("target")] if graph_record else []

            # 第二步：查询当前用户的学习进度和画像
            # 第二步：查询当前用户的学习进度和画像 (引入自愈机制)
            user_query = """
                    MERGE (u:User {id: $user_id})
                    WITH u
                    OPTIONAL MATCH (u)-[r:UNDERSTANDS]->(c:Concept)
                    RETURN
                        u.frustration_level AS frustration,
                        u.bad_code_smells AS bad_smells,
                        collect(DISTINCT {concept: c.name, status: r.status}) AS skills
            """
            user_result = await session.run(user_query, user_id=user_id)
            user_record = await user_result.single()

            if not user_record:
                return {"message": "User not found.", "profile": None}

            # 洗掉未关联任何技能时产生的空数据
            clean_skills = [s for s in user_record["skills"] if s.get("concept")]

            # 第三步：组装完美契合前端的 JSON 返回体
            return {
                "user_id": user_id,
                "frustration_level": user_record["frustration"],
                "bad_code_smells": user_record["bad_smells"],
                "graph_schema": {  # 前端用这个渲染全量图谱网格
                    "nodes": nodes,
                    "dependencies": dependencies
                },
                "skills": clean_skills  # 前端用这个给节点上色 (点亮状态)
            }
        except Exception as e:
            logger.error(f"❌ 查询图谱失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="查询失败")


# ==========================================
# 接口 2: 增量更新/覆盖技能树 (POST)
# ==========================================
@router.post("/mastery")
async def update_user_mastery(request: MasteryUpdateRequest):
    """用户手动自评技能熟练度（3态模式）"""
    driver = AsyncNeo4jClient.get_driver()

    # 将三种状态的数据分开，使用不同的 Cypher 策略处理
    to_mastered = [item.concept for item in request.skill_updates if item.state == "mastered"]
    to_progressing = [item.concept for item in request.skill_updates if item.state == "progressing"]
    to_unlearned = [item.concept for item in request.skill_updates if item.state == "unlearned"]

    async with driver.session(database="neo4j") as session:
        try:
            # 1. 处理 Mastered (完全放行)
            if to_mastered:
                await session.run("""
                    UNWIND $concepts AS c_name
                    MERGE (u:User {id: $user_id})
                    MERGE (c:Concept {name: c_name})
                    MERGE (u)-[r:UNDERSTANDS]->(c)
                    SET r.status = "mastered", r.error_weight = 0, r.source = "manual"
                """, user_id=request.user_id, concepts=to_mastered)

            # 2. 处理 Progressing (注入防呆提示)
            if to_progressing:
                await session.run("""
                    UNWIND $concepts AS c_name
                    MERGE (u:User {id: $user_id})
                    MERGE (c:Concept {name: c_name})
                    MERGE (u)-[r:UNDERSTANDS]->(c)
                    SET r.status = "progressing", 
                        r.error_weight = 3, 
                        r.error_pattern = "用户自评：懂概念但缺乏实战，需防范边界条件Bug。",
                        r.source = "manual"
                """, user_id=request.user_id, concepts=to_progressing)

            # 3. 处理 Unlearned (物理抹除连线，让雷达重新拦截)
            if to_unlearned:
                await session.run("""
                    UNWIND $concepts AS c_name
                    MATCH (u:User {id: $user_id})-[r:UNDERSTANDS]->(c:Concept {name: c_name})
                    DELETE r
                """, user_id=request.user_id, concepts=to_unlearned)

            logger.info(f"✅ 用户 {request.user_id} 手动同步了技能树。")
            return {"message": "同步成功"}
        except Exception as e:
            logger.error(f"❌ 技能树更新失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="更新失败")


# ==========================================
# 接口 3: 危险操作 - 重置图谱 (DELETE)
# ==========================================
@router.delete("/mastery/{user_id}")
async def reset_user_graph(user_id: int):
    """一键洗白：删除用户的所有知识图谱连线（但不删除 User 节点本身）"""
    query = """
    MATCH (u:User {id: $user_id})-[r:UNDERSTANDS]->()
    DELETE r
    """
    driver = AsyncNeo4jClient.get_driver()
    async with driver.session(database="neo4j") as session:
        try:
            await session.run(query, user_id=user_id)
            # 顺便把情绪指标和坏习惯清空
            await session.run("MATCH (u:User {id: $user_id}) REMOVE u.frustration_level, u.bad_code_smells",
                              user_id=user_id)
            logger.info(f"⚠️ 用户 {user_id} 的图谱已被一键重置。")
            return {"message": "图谱已重置为空白状态。"}
        except Exception as e:
            logger.error(f"❌ 重置图谱失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="重置失败")
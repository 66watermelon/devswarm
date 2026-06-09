"""
DevSwarm GraphRAG 读取器 (GraphReader)

核心职责：
1. 根据 user_id 异步查询 Neo4j 图数据库。
2. 提取用户的行为画像（红温指数、坏习惯）。
3. 提取用户的错题本（过滤已掌握，按错误权重降序，只取 Top 10）。
4. 将复杂的图谱结构降维格式化为大模型极易阅读的 Markdown 文本。
"""

import logging
from typing import Optional

from db.neo4j_client import AsyncNeo4jClient

logger = logging.getLogger(__name__)


class GraphReader:

    @staticmethod
    async def get_user_memory_context(user_id: int) -> str:
        """
        供 Agent 节点调用的核心入口点。
        如果读取失败或该用户是全新用户，将优雅降级，返回空字符串。
        """
        driver = AsyncNeo4jClient.get_driver()

        # 开启异步读事务 (Read Transaction，大厂规范：读写分离，提升吞吐量)
        async with driver.session(database="neo4j") as session:
            try:
                result = await session.execute_read(GraphReader._cypher_read_memory, user_id)
                return GraphReader._format_memory_to_text(result)
            except Exception as e:
                logger.error(f"❌ [GraphReader] 读取用户 {user_id} 图谱记忆失败: {e}", exc_info=True)
                return ""  # 致命防御：图数据库挂了绝不能影响聊天主流程

    @staticmethod
    async def _cypher_read_memory(tx, user_id: int) -> Optional[dict]:
        """执行极度优化的 Cypher 查询 。"""
        query = """
            MATCH (u:User {id: $user_id})
            OPTIONAL MATCH (u)-[r:UNDERSTANDS]->(c:Concept)
            RETURN 
                u.frustration_level AS frustration,
                u.bad_code_smells AS bad_smells,
                collect({
                    concept: c.name,
                    category: c.category,
                    status: r.status,
                    weight: r.error_weight,
                    pattern: r.error_pattern
                }) AS concepts
            """
        result = await tx.run(query, user_id=user_id)

        record = await result.single()

        if not record:
            return None

        # 4. 在内存中进行轻量级过滤与排序
        all_concepts = [c for c in record["concepts"] if c.get("concept") is not None]
        weak_concepts = [c for c in all_concepts if c.get("status") != "mastered"]
        sorted_weak_concepts = sorted(weak_concepts, key=lambda x: x.get("weight", 0), reverse=True)[:10]

        return {
            "frustration": record["frustration"],
            "bad_smells": record["bad_smells"],
            "weak_concepts": sorted_weak_concepts
        }

    @staticmethod
    def _format_memory_to_text(memory_dict: Optional[dict]) -> str:
        """
        将字典数据转换为 LLM 极其敏感的 Prompt 结构化片段。
        """
        if not memory_dict:
            return ""

        context_lines = ["<User_Cognitive_Profile>"]

        # --- 1. 注入情绪与心智画像 ---
        frust = memory_dict.get("frustration")
        if frust is not None:
            context_lines.append(f"- 历史受挫指数 (1-5): {frust}")
            # 情感干预触发器
            if frust >= 4:
                context_lines.append("  [⚠️系统警告：该用户近期极易红温，请在指导时极度耐心，多给予情绪价值鼓励！]")

        # --- 2. 注入工程坏味道 ---
        smells = memory_dict.get("bad_smells")
        if smells:
            context_lines.append(f"- 历史工程坏习惯: {', '.join(smells)}")

        # --- 3. 注入薄弱知识点清单 ---
        weak_concepts = memory_dict.get("weak_concepts", [])
        if weak_concepts:
            context_lines.append("- 历史知识点掌握档案 (按易错程度降序):")
            for c in weak_concepts:
                # 拼接单行描述
                line = f"  * 【{c.get('category')} - {c.get('concept')}】 状态: {c.get('status')} | 错误权重: {c.get('weight')}"
                if c.get("pattern"):
                    line += f" | 常见错误模式: '{c.get('pattern')}'"
                context_lines.append(line)

        context_lines.append("</User_Cognitive_Profile>")

        # 如果中间没有任何有效数据（只有头尾两个标签），直接返回空
        if len(context_lines) <= 2:
            return ""

        return "\n".join(context_lines)

    # =========================================================================
    # 多跳溯源雷达：自适应学习路径的核心探测器
    # =========================================================================

    @staticmethod
    async def check_prerequisites(user_id: int, target_concept: str) -> dict:
        """
        供 Agent 节点调用的“多跳雷达”入口点。
        检查用户对当前准备挑战的算法（target_concept）的前置依赖是否全部达标。

        返回:
            dict: 包含全量缺失知识点和内部依赖链条的字典。
                  格式: {"missing_concepts": list[str], "dependency_edges": list[dict]}
        """
        if not target_concept:
            return {"missing_concepts": [], "dependency_edges": []}

        driver = AsyncNeo4jClient.get_driver()

        async with driver.session(database="neo4j") as session:
            try:
                missing_prereqs = await session.execute_read(
                    GraphReader._cypher_check_prereqs, user_id, target_concept
                )
                return missing_prereqs
            except Exception as e:
                logger.error(f"❌ [GraphReader] 多跳雷达扫描失败 (目标: {target_concept}): {e}", exc_info=True)
                return {"missing_concepts": [], "dependency_edges": []}


    @staticmethod
    async def _cypher_check_prereqs(tx, user_id: int, target_concept: str) -> dict:
        """雷达底层的高阶拓扑多跳执行逻辑。

        不仅查出直接前置，还会无限向上追溯所有祖先依赖，并还原缺失节点之间的依赖链条。
        """
        query = """
            MATCH (target:Concept {name: $target_concept})
            MATCH (u:User {id: $user_id})

            // 1. 顺藤摸瓜：使用变长路径 (*1..5) 向上狂追 1 到 5 层的所有祖先知识点
            MATCH (prereq:Concept)-[:PREREQUISITE_FOR*1..5]->(target)
            WITH DISTINCT prereq, u

            // 2. 灵魂拷问：看看用户对这些所有代际的知识点的掌握情况
            OPTIONAL MATCH (u)-[r:UNDERSTANDS]->(prereq)

            // 3. 提纯过滤：只留下用户【未掌握】或者【根本不知道】的节点
            WHERE r IS NULL OR r.status <> 'mastered'
            WITH collect(prereq) AS missing_nodes

            // 4. 关键降维打击：在这些缺失的节点内部，找出它们彼此之间的直接依赖边（还原链条）
            OPTIONAL MATCH (n1:Concept)-[:PREREQUISITE_FOR]->(n2:Concept)
            WHERE n1 IN missing_nodes AND n2 IN missing_nodes

            // 5. 返回缺失的知识点列表，以及它们之间的进化关系网
            RETURN 
                [n IN missing_nodes | n.name] AS missing_concepts,
                collect(DISTINCT {from: n1.name, to: n2.name}) AS dependency_edges
        """
        result = await tx.run(query, user_id=user_id, target_concept=target_concept)
        record = await result.single()

        if not record:
            return {"missing_concepts": [], "dependency_edges": []}

        data = record.data()

        return {
            "missing_concepts": data.get("missing_concepts", []),
            "dependency_edges": data.get("dependency_edges", [])
        }

    # =========================================================================
    # 蜂群雷达：基于图谱前置门禁的群体协同过滤 (Swarm Collaborative Filtering)
    # =========================================================================

    @staticmethod
    async def get_swarm_recommendations(user_id: int) -> list[dict]:
        """
        供上层业务或前端拉取“蜂群雷达”推荐的入口。
        如果发生错误或没有符合条件的推荐，返回空列表。

        Returns:
            list[dict]: 推荐列表，例如 [{"concept": "并查集", "peer_count": 12}, ...]
        """
        driver = AsyncNeo4jClient.get_driver()

        async with driver.session(database="neo4j") as session:
            try:
                records = await session.execute_read(
                    GraphReader._cypher_swarm_recommendations, user_id
                )
                return records
            except Exception as e:
                logger.error(f"❌ [GraphReader] 蜂群雷达扫描失败 (用户: {user_id}): {e}", exc_info=True)
                return []

    @staticmethod
    async def _cypher_swarm_recommendations(tx, user_id: int) -> list[dict]:
        """
        底层 Cypher 执行逻辑：
        1. 找同类 (Mastered 交集 > 60%)
        2. 找热点 (同类近 30 天掌握的新知识点)
        3. 卡门禁 (用户必须具备该热点知识的全部直接前置)
        4. 按热度降序，返回 Top 3
        """
        query = """
            // 【步骤 1】先找到用户 A 掌握的知识点，打包成集合 (a_concepts)
            MATCH (a:User {id: $user_id})-[rA:UNDERSTANDS {status: 'mastered'}]->(c:Concept)
            WITH a, collect(c.name) AS a_concepts, count(c) AS a_count

            // 防御：如果用户 A 一个知识点都没掌握，直接阻断，防止除以 0
            WHERE a_count > 0

            // 【步骤 2】顺藤摸瓜找同类，并过滤相似度 > 60% 的用户 (User B)
            MATCH (b:User)-[:UNDERSTANDS {status: 'mastered'}]->(shared:Concept)
            WHERE b.id <> a.id AND shared.name IN a_concepts
            WITH a, a_concepts, a_count, b, count(shared) AS shared_count
            WHERE toFloat(shared_count) / a_count > 0.60

            // 【步骤 3】找到这群 B 在近 30 天内掌握的、且 A 还没学过的知识点 (rec)
            MATCH (b)-[rNew:UNDERSTANDS {status: 'mastered'}]->(rec:Concept)
            WHERE NOT rec.name IN a_concepts
              AND duration.between(rNew.last_updated, datetime()).days <= 30

            // 【步骤 4】绝对前置门禁：找 rec 的所有前置，要求 A 必须全掌握了
            OPTIONAL MATCH (pre:Concept)-[:PREREQUISITE_FOR]->(rec)
            WITH b, rec, a_concepts, collect(pre.name) AS prereqs
            WHERE all(p IN prereqs WHERE p IN a_concepts) OR size(prereqs) = 0

            // 【步骤 5】按掌握该知识点的“同类人数”降序排列，取 Top 3
            RETURN 
                rec.name AS concept, 
                count(DISTINCT b) AS peer_count
            ORDER BY peer_count DESC
            LIMIT 3
        """
        result = await tx.run(query, user_id=user_id)

        # 提取数据，返回结构化列表
        records = [record.data() async for record in result]
        return records

    # =========================================================================
    # 网关专属：纯净版知识点与掌握程度读取 (供 Intent 节点调用，挂载到 State)
    # =========================================================================

    @staticmethod
    async def fetch_user_knowledge_profile(user_id: int) -> str:
        """
        专门供网关调用的独立接口。
        仅提取用户的知识点和掌握程度，不查询情绪和坏习惯。
        """
        driver = AsyncNeo4jClient.get_driver()
        async with driver.session(database="neo4j") as session:
            try:
                result = await session.execute_read(GraphReader._cypher_fetch_knowledge_only, user_id)
                return GraphReader._format_knowledge_only_to_text(result)
            except Exception as e:
                logger.error(f"❌ [GraphReader] 获取用户 {user_id} 知识掌握情况失败: {e}", exc_info=True)
                return ""

    @staticmethod
    async def _cypher_fetch_knowledge_only(tx, user_id: int) -> Optional[dict]:
        """纯净版 Cypher 查询：只查知识点和状态，剔除其他干扰数据"""
        query = """
            MATCH (u:User {id: $user_id})-[r:UNDERSTANDS]->(c:Concept)
            RETURN collect({
                concept: c.name,
                category: c.category,
                status: r.status,
                weight: r.error_weight,
                pattern: r.error_pattern
            }) AS concepts
        """
        result = await tx.run(query, user_id=user_id)
        record = await result.single()

        # 如果没有查到任何知识点关联
        if not record or not record.get("concepts"):
            return None

        all_concepts = [c for c in record["concepts"] if c.get("concept") is not None]

        # 分离出已掌握和未掌握的知识点
        mastered_concepts = [c.get("concept") for c in all_concepts if c.get("status") == "mastered"]
        weak_concepts = [c for c in all_concepts if c.get("status") != "mastered"]

        # 对薄弱知识点按错误权重降序排列
        sorted_weak_concepts = sorted(weak_concepts, key=lambda x: x.get("weight", 0), reverse=True)

        return {
            "mastered_concepts": mastered_concepts,
            "weak_concepts": sorted_weak_concepts
        }

    @staticmethod
    def _format_knowledge_only_to_text(profile_dict: Optional[dict]) -> str:
        """格式化为纯净的知识点画像字符串"""
        if not profile_dict:
            return ""

        context_lines = ["<User_Knowledge_Profile>"]

        # 1. 注入已掌握的知识面
        mastered = profile_dict.get("mastered_concepts", [])
        if mastered:
            context_lines.append(f"- 已掌握知识点: {', '.join(mastered)}")
        else:
            context_lines.append("- 已掌握知识点: 无 (当前基础极度薄弱)")

        # 2. 注入薄弱知识点及其掌握程度
        weak_concepts = profile_dict.get("weak_concepts", [])
        if weak_concepts:
            context_lines.append("- 薄弱/学习中知识点 (按易错程度降序):")
            for c in weak_concepts:
                line = f"  * 【{c.get('category')} - {c.get('concept')}】 状态: {c.get('status')} | 错误权重: {c.get('weight')}"
                if c.get("pattern"):
                    line += f" | 常见错误模式: '{c.get('pattern')}'"
                context_lines.append(line)

        context_lines.append("</User_Knowledge_Profile>")

        if len(context_lines) <= 2:
            return ""

        return "\n".join(context_lines)
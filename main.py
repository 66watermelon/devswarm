"""
DevSwarm 算法推演平台 —— 应用入口 (main.py)

职责：
- 初始化 FastAPI 应用实例（纯装配车间，不含业务逻辑）
- 管理 PostgreSQL 连接池与 Checkpointer 生命周期（LangGraph 长期记忆）
- 配置全局中间件（CORS 等）
- 注册所有子路由（认证 / 智能体推演 / 健康检查）
- 提供 uvicorn 启动入口

启动方式:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
    或直接运行: python main.py
"""

import logging
from pathlib import Path
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from core.limiter import limiter

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
logger = logging.getLogger(__name__)

# ================================================================
# 1. 生命周期管理 —— PostgreSQL 连接池 & Checkpointer
# ================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI 应用生命周期：启动时初始化各项基础设施，关闭时安全释放资源。"""

    # 局部导入：避免循环依赖
    from db.postgres_client import pg_pool
    from main_graph import init_graph  # 【修改】导入延迟初始化函数
    from db.redis_client import redis_async
    from db.neo4j_client import AsyncNeo4jClient

    logger.info("[Lifespan] 正在启动 DevSwarm 核心引擎，准备拉起底层基建...")

    try:
        # ==========================================
        # [启动阶段] 资源预热与连通性检查
        # ==========================================

        # 1. 开启 PostgreSQL 物理连接池
        logger.info("[Lifespan] 正在启动生产级 PostgreSQL 连接池...")
        await pg_pool.open()

        # 2. 延迟初始化图与检查点（此时事件循环已经在安全运行了）
        logger.info("[Lifespan] 正在初始化 LangGraph 执行图与 Postgres 检查点...")
        await init_graph()

        # 3. 初始化 Neo4j 图数据库连接池 (读取 .env 并测试连通性)
        await AsyncNeo4jClient.connect()

        logger.info("[Lifespan] 所有基建 (PostgreSQL, Redis, Neo4j) 预热完成！")

    except Exception as e:
        logger.error(f"❌ [Lifespan] 严重错误：应用启动时资源初始化失败！原因: {e}")
        raise e

    yield

    # ==========================================
    # [关闭阶段] 停机与资源回收 (Graceful Shutdown)
    # ==========================================
    logger.info("[Lifespan] 收到停机信号，正在清理并释放系统资源...")

    try:
        # 1. 优雅释放 PostgreSQL 连接池
        logger.info("[Lifespan] 正在安全释放 PostgreSQL 连接池...")
        await pg_pool.close()

        # 2. 释放 Redis 连接
        await redis_async.aclose()

        # 3. 释放 Neo4j 连接池
        await AsyncNeo4jClient.close()

        logger.info("[Lifespan] 所有数据库连接已安全切断，完美下线。")
    except Exception as e:
        logger.error(f"⚠️ [Lifespan] 释放资源时发生异常，可能存在连接泄漏: {e}")


# ================================================================
# 2. FastAPI 应用实例初始化
# ================================================================

app = FastAPI(
    title="DevSwarm AI Workbench",
    description="Multi-Agent 算法推演平台 —— 后端 API 服务",
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ================================================================
# 3. 全局中间件注册
# ================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================================================
# 3.5 速率限制（IP 维度，内存存储，单 worker 安全）
# ================================================================

app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)


# ================================================================
# 4. 子路由注册
# ================================================================

from api.routes.auth_routes import router as auth_router
app.include_router(auth_router, tags=["用户认证"])

from api.routes.chat_routes import router as chat_router
app.include_router(chat_router, prefix="/api/chat", tags=["智能体推演"])

from api.routes.graph_routes import router as graph_router
app.include_router(graph_router, prefix="/api/graph", tags=["知识图谱"])

from api.routes.user_routes import router as user_router
app.include_router(user_router, prefix="/api/users", tags=["用户个人信息"])

# --- 健康检查 ---
@app.get("/api/health", tags=["系统"])
async def health_check():
    """服务健康检查。"""
    return {"status": "ok", "service": "DevSwarm AI Workbench", "version": "2.1.0"}


# ================================================================
# 5. 启动入口
# ================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
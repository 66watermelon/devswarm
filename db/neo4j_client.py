"""
DevSwarm 图数据库引擎 (Neo4j Async Client)

核心机制：
- 采用严格的异步单例模式 (Singleton) 管理连接池。
- 由 FastAPI 的 lifespan 统一管理连接与销毁。
- 全局使用 AsyncGraphDatabase 告别 I/O 阻塞。
"""

import logging
from typing import Optional
from neo4j import AsyncGraphDatabase, AsyncDriver
from core.config import settings

logger = logging.getLogger(__name__)


class AsyncNeo4jClient:
    """Neo4j 异步客户端单例管理器"""

    _driver: Optional[AsyncDriver] = None

    @classmethod
    async def connect(cls) -> None:
        """初始化连接池，并确保失败时不会残留僵尸连接。"""
        if cls._driver is None:
            try:
                cls._driver = AsyncGraphDatabase.driver(
                    settings.NEO4J_URI,
                    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
                )
                await cls._driver.verify_connectivity()
                logger.info("✅ 成功连接到 Neo4j 图数据库！")
            except Exception as e:
                logger.error(f"❌ Neo4j 连接失败: {e}", exc_info=True)

                if cls._driver is not None:
                    try:
                        await cls._driver.close()  # 尝试关闭底层的 TCP Socket
                    except Exception:
                        pass
                    cls._driver = None  # 绝对清空指针

                raise e

    @classmethod
    async def close(cls) -> None:
        """
        关闭连接池。
        必须在 FastAPI 关闭时 (lifespan 结束) 调用此方法。
        """
        if cls._driver is not None:
            try:
                await cls._driver.close()
                cls._driver = None
                logger.info("🛑 Neo4j 连接池已优雅关闭。")
            except Exception as e:
                logger.error(f"⚠️ Neo4j 关闭时发生异常: {e}")

    @classmethod
    def get_driver(cls) -> AsyncDriver:
        """
        供业务层 (如 GraphReader, GraphWriter) 获取驱动实例。
        如果驱动未初始化，直接抛出致命错误。
        """
        if cls._driver is None:
            raise RuntimeError(
                "Neo4j 驱动未初始化！请确保在 FastAPI 的 lifespan 中调用了 AsyncNeo4jClient.connect()"
            )
        return cls._driver
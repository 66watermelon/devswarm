"""
DevSwarm Auth 模块 —— 数据库与缓存引擎 (双擎版：兼容同步与纯异步)

初始化 SQLAlchemy 同步/异步引擎、会话工厂，以及 Redis 客户端。
提供 init_db() 自动建表函数。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import redis as redis_lib
import redis.asyncio as aioredis # 🌟 引入纯异步的 Redis 客户端

from core.config import settings

# ---------------------------------------------------------------------------
# SQLAlchemy 引擎 & 会话工厂 (传统同步版 - 供老接口和启动脚本使用)
# ---------------------------------------------------------------------------

engine = create_engine(settings.SQLALCHEMY_DATABASE_URI, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ---------------------------------------------------------------------------
# SQLAlchemy 引擎 & 会话工厂 (全新异步版 - 供高并发流式推演接口使用)
# ---------------------------------------------------------------------------

# 将传统的 MySQL 同步驱动替换为异步驱动 (aiomysql)
# 假设你的 URI 是 mysql:// 或 mysql+pymysql://，这里将其动态替换为 mysql+aiomysql://
ASYNC_SQLALCHEMY_DATABASE_URI = (
    settings.SQLALCHEMY_DATABASE_URI
    .replace("mysql://", "mysql+aiomysql://")
    .replace("mysql+pymysql://", "mysql+aiomysql://")
)

# create_async_engine: 创建纯异步引擎，告别事件循环阻塞
async_engine = create_async_engine(
    settings.ASYNC_SQLALCHEMY_DATABASE_URI,
    echo=False,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10
)


# async_sessionmaker: 生成 AsyncSession
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession
)

# ---------------------------------------------------------------------------
# SQLAlchemy 2.0 DeclarativeBase
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类，所有 ORM 模型统一继承。"""
    pass

# ---------------------------------------------------------------------------
# Redis 客户端 (双擎版)
# ---------------------------------------------------------------------------

# 1. 传统同步 Redis (供老接口使用)
redis_client = redis_lib.Redis.from_url(settings.REDIS_URL, decode_responses=True)

# 2. 全新异步 Redis (供 deps.py 鉴权、流式推演使用)
async_redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)


# ---------------------------------------------------------------------------
# 依赖注入辅助函数
# ---------------------------------------------------------------------------

def get_db() -> Session:
    """FastAPI 同步依赖注入：获取传统数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_async_db():
    """FastAPI 异步依赖注入：获取异步数据库会话

    所有定义为 `async def` 的高并发接口，必须使用此依赖！
    """
    async with AsyncSessionLocal() as session:
        yield session

def init_db() -> None:
    """自动建表：利用同步引擎在系统启动时建表"""
    Base.metadata.create_all(bind=engine)
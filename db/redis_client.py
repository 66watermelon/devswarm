"""
DevSwarm 流式推演专用 Redis 客户端

提供全局异步 Redis 连接池单例，专用于 CQRS Pub/Sub 流式推演。
与鉴权模块使用的 Redis（db/database.py）分离部署，互不影响。

生命周期由 main.py 的 lifespan 管理：
- 启动时：模块导入即建立连接池
- 关闭时：调用 redis_async.aclose() 释放
"""

import redis.asyncio as aioredis

redis_async: aioredis.Redis = aioredis.Redis.from_url(
    "redis://localhost:6380/1",
    max_connections=20,
    decode_responses=True,
)

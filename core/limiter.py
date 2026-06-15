"""
DevSwarm 速率限制模块

全局单例 Limiter，供 main.py 注册异常处理器、路由文件注册装饰器。
存储后端：Redis 6380 db 2（多 worker 安全，与 Pub/Sub 同实例不同库）。
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="redis://localhost:6380/2",
    default_limits=["60/minute"],
)

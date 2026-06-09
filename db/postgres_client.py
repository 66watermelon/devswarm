import os
from psycopg_pool import AsyncConnectionPool

# 1. 从你的环境变量或 core/config 中读取，做到配置与代码分离
PG_CHECKPOINT_URI = os.getenv(
    "POSTGRES_URL",
    "postgresql://admin:123456@localhost:5432/main_db?sslmode=disable"
)

connection_kwargs = {
    "autocommit": True,
    "prepare_threshold": 0,
}

# 2. 对外暴露一个全局唯一的、安全可导入的单例连接池实例
pg_pool = AsyncConnectionPool(
    conninfo=PG_CHECKPOINT_URI,
    max_size=20,
    kwargs=connection_kwargs,
    open=False   # 保持关闭，由外部 lifespan 统一控制生命周期
)
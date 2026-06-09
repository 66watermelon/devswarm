"""
DevSwarm 全局统一配置模块
基于 pydantic-settings 构建。自动从根目录 .env 文件加载环境变量。
"""

from __future__ import annotations
from pathlib import Path

from dotenv import load_dotenv
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 动态定位到项目根目录下的 .env 文件
# (当前文件在 devswarm_core/core/config.py，parent.parent 即为 devswarm_core/)
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# 将 .env 中所有变量注入 os.environ，确保 LangSmith / 第三方库能读取
load_dotenv(_ENV_FILE, override=False)

class Settings(BaseSettings):
    # 配置 Pydantic 自动去 _ENV_FILE 读取环境变量
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,  # 环境变量忽略大小写匹配
        extra="ignore",        # 忽略 .env 中多余的无效变量
    )

    # ==========================================
    # 1. 项目基础配置
    # ==========================================
    PROJECT_NAME: str = "DevSwarm AI Workbench"
    API_V1_STR: str = "/api"

    # ==========================================
    # 2. MySQL 数据库配置 (双引擎支撑)
    # ==========================================
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "090508"
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_DB: str = "devswarm"

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """自动拼接 SQLAlchemy 传统同步连接字符串 (供建表与老接口使用)"""
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
        )

    @computed_field
    @property
    def ASYNC_SQLALCHEMY_DATABASE_URI(self) -> str:
        """自动拼接 SQLAlchemy 纯异步连接字符串 (供高并发流式推演接口使用)"""
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
        )

    # ==========================================
    # 3. Redis 缓存配置
    # ==========================================
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 1

    @computed_field
    @property
    def REDIS_URL(self) -> str:
        """自动拼接 Redis 连接字符串"""
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ==========================================
    # 4. JWT 安全认证配置
    # ==========================================
    SECRET_KEY: str = "devswarm-jwt-secret-change-in-production"  # 强烈建议在 .env 中设置复杂随机字符串
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 默认 24 小时过期
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24

    # ==========================================
    # 5. LLM 大模型引擎配置
    # ==========================================
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL_NAME: str = "deepseek-v4-pro"
    LLM_TIMEOUT: int = 120  # API 请求与沙箱熔断超时时间

    # ==========================================
    # 6. Neo4j 图数据库配置
    # ==========================================
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "" # 留空或填默认密码，真实密码由 .env 覆盖


    # ==========================================
    # 7. PostgreSQL 数据库配置 
    # ==========================================
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "admin"
    POSTGRES_PASSWORD: str = "123456"
    POSTGRES_DB: str = "main_db"
    POSTGRES_SSLMODE: str = "disable"

    @computed_field
    @property
    def POSTGRES_URL(self) -> str:
        """自动拼接 PostgreSQL 连接字符串 (供 LangGraph 长期记忆专属的 psycopg 驱动使用)"""
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            f"?sslmode={self.POSTGRES_SSLMODE}"
        )


# 实例化全局单例
settings = Settings()
"""
DevSwarm Auth 模块 —— ORM 数据模型

定义 User（用户）核心实体。
采用 SQLAlchemy 2.0 DeclarativeBase 风格。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text,
)
from sqlalchemy.orm import relationship

from db.database import Base
from models import thread

class User(Base):
    """用户表 —— 存储注册用户的基本信息。

    Attributes:
        id: 自增主键。
        username: 用户名（唯一索引，不可为空）。
        hashed_password: bcrypt 加密后的密码哈希值。
        created_at: 注册时间（UTC）。
    """

    __tablename__ = "users"

    # ---- 字段定义 ----
    id = Column(Integer, primary_key=True, autoincrement=True, comment="用户自增主键")
    username = Column(
        String(64), unique=True, nullable=False, index=True, comment="用户名（唯一）"
    )
    hashed_password = Column(String(256), nullable=False, comment="bcrypt 加密密文")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="注册时间",
    )

    # ---- 关联关系 ----
    # 级联删除：删除用户时自动删除其所有对话线程
    threads = relationship(
        "Thread", back_populates="owner", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}')>"




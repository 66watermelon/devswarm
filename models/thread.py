"""
DevSwarm Auth 模块 —— ORM 数据模型

定义 Thread（对话线程）核心实体。
采用 SQLAlchemy 2.0 DeclarativeBase 风格。
"""


import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text,
)
from sqlalchemy.orm import relationship
from models import user
from db.database import Base


class Thread(Base):
    """对话线程表 —— 记录用户与 AI 的每次算法推演会话。

    Attributes:
        id: UUID 字符串主键。
        user_id: 所属用户的外键。
        title: 对话标题（可由首条消息自动生成）。
        created_at: 创建时间（UTC）。
    """

    __tablename__ = "threads"

    # ---- 字段定义 ----
    id = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
        comment="UUID 主键",
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属用户 ID",
    )
    title = Column(String(256), nullable=False, default="新对话", comment="对话标题")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="创建时间",
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="最后更新时间",
    )

    # ---- 关联关系 ----
    owner = relationship("User", back_populates="threads")

    def __repr__(self) -> str:
        return f"<Thread(id={self.id}, title='{self.title}')>"
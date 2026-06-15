"""
DevSwarm Chat 模块 —— Pydantic 请求/响应校验模型

定义 Thread（对话线程）和 Stream 相关的数据结构。
"""

from datetime import datetime
from typing import Optional
import re

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Thread 请求模型
# ---------------------------------------------------------------------------

class ThreadCreateRequest(BaseModel):
    """创建新会话的请求体。

    Attributes:
        title: 会话标题（可由前端从首条消息截取）。
    """
    title: str = Field(
        ..., min_length=1, max_length=256,
        description="会话标题",
    )


class StreamRequest(BaseModel):
    """流式推演请求体。

    Attributes:
        prompt: 用户输入的算法题目或提问。
        thread_id: 关联的会话 ID（前端在首轮消息前已懒创建，此处为必填）。
        user_code: 诊断模式下用户提供的待调试代码（可选）。
    """
    prompt: str = Field(
        ..., min_length=1, max_length=10000,
        description="用户输入的算法题目或提问（上限 5000 字符）",
    )
    thread_id: str = Field(..., min_length=1, description="关联的会话 ID")
    user_code: Optional[str] = Field(
        None, max_length=20000,
        description="诊断模式下用户提供的待调试代码（上限 20000 字符）",
    )

    @field_validator("prompt")
    @classmethod
    def sanitize_prompt(cls, v: str) -> str:
        """移除不可见控制字符，拒绝常见 prompt injection 关键字。"""
        # 去掉 ASCII 控制字符（保留换行 \n 和制表 \t）
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', v)
        # 拒绝明显的 prompt injection 关键字
        blocked = ["ignore previous", "system prompt", "<<SYS>>", "<|im_start|>"]
        lower = cleaned.lower()
        for kw in blocked:
            if kw in lower:
                raise ValueError("输入包含不安全的指令")
        return cleaned


# ---------------------------------------------------------------------------
# Thread 响应模型
# ---------------------------------------------------------------------------

class ThreadResponse(BaseModel):
    """会话信息响应体。

    Attributes:
        id: UUID 主键。
        user_id: 所属用户 ID。
        title: 对话标题。
        created_at: 创建时间（UTC）。
        updated_at: 最后更新时间（UTC）。
    """
    id: str
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

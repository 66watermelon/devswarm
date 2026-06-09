"""
DevSwarm 智能体推演路由

提供:
- POST /api/chat/threads   创建新会话
- GET  /api/chat/threads   拉取历史会话列表
- POST /api/chat/stream    JWT 鉴权流式推演（CQRS + Redis 锁 + Pub/Sub）
- GET  /api/chat/history   拉取指定会话的历史消息（从 Checkpoint 还原）

架构 (v5 Clean Architecture):
  路由层只负责：鉴权 → 参数校验 → 调 service → 返回响应。
  所有业务逻辑已提取到 services/、core/utils/、db/ 中。
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from starlette.responses import StreamingResponse

from api.deps import get_current_user, get_async_db
from models import User, Thread
from schemas.chat import ThreadCreateRequest, ThreadResponse, StreamRequest

import main_graph
from core.utils.message_utils import clean_messages
from db.redis_client import redis_async
from services.stream_service import run_graph_worker, sse_consumer

logger = logging.getLogger(__name__)
router = APIRouter(tags=["智能体推演"])


# ================================================================
# 路由端点
# ================================================================

@router.post("/threads", response_model=ThreadResponse, summary="创建新会话")
async def create_thread(
    body: ThreadCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """创建新的对话线程。"""
    thread = Thread(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=body.title,
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return thread


@router.get("/threads", response_model=List[ThreadResponse], summary="拉取历史会话列表")
async def list_threads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """拉取当前用户的所有会话，按 updated_at 降序排列。"""
    stmt = (
        select(Thread)
        .filter(Thread.user_id == current_user.id)
        .order_by(desc(Thread.updated_at))
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/stream", summary="JWT 鉴权流式推演（CQRS + Redis 锁 + 记忆吸收）")
async def chat_stream(
    body: StreamRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """POST 流式对话接口 —— CQRS 架构。

    1. JWT 鉴权 + Thread 所有权校验
    2. Redis SETNX 分布式锁防并发
    3. BackgroundTasks 启动 Worker 跑图
    4. 返回 StreamingResponse（订阅 Redis Pub/Sub）
    """
    if not body.thread_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少 thread_id，请先创建会话。",
        )

    # 校验会话所有权
    stmt = select(Thread).filter(Thread.id == body.thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_first()

    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="会话不存在")
    if thread.user_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="无权访问该会话")

    thread.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # 分布式锁
    lock_key = f"lock:stream:{body.thread_id}"
    acquired = await redis_async.set(lock_key, "1", nx=True, ex=600)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该会话正在推演中，请等待当前推演完成后再试。",
        )

    # 启动后台 Worker
    channel = f"stream:{body.thread_id}"
    background_tasks.add_task(
        run_graph_worker,
        prompt=body.prompt,
        thread_id=body.thread_id,
        user_id=current_user.id,
        channel=channel,
        lock_key=lock_key,
        user_code=body.user_code or "",
    )

    return StreamingResponse(
        sse_consumer(channel, lock_key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history", summary="拉取会话历史消息")
async def get_thread_history(
    thread_id: str = Query(..., description="会话 UUID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """从 LangGraph Checkpoint 中还原指定会话的完整状态。"""
    stmt = select(Thread).filter(Thread.id == thread_id)
    result = await db.execute(stmt)
    thread = result.scalar_first()

    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="会话不存在")
    if thread.user_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="无权访问该会话")

    config = {"configurable": {"thread_id": thread_id}}
    state = await main_graph.app.aget_state(config)

    if state is None or state.values is None:
        return {"messages": [], "current_code": "", "qa_feedback": ""}

    values = state.values
    return {
        "messages": clean_messages(values.get("messages", [])),
        "current_code": values.get("generated_code", "") or "",
        "qa_feedback": values.get("execution_feedback", "") or "",
    }

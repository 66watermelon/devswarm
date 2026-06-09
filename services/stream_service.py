"""
DevSwarm 流式推演服务

提供：
- run_graph_worker: 后台跑图 Worker（LangGraph 执行 + Redis Pub/Sub 广播）
- sse_consumer: 前端 SSE 消费者（订阅 Redis 频道，yield 给 HTTP 响应）

CQRS 架构核心：
  Worker 与 HTTP 响应协程完全解耦，客户端断开不中断图流转。
"""

import asyncio
import traceback
from typing import AsyncGenerator, Optional

import redis.asyncio as aioredis
from langchain_core.messages import HumanMessage

import main_graph
from core.engine.state import DevState
from core.constants import EOF_MARKER, SKIP_NODES, NODE_DISPLAY_MAP
from core.utils.sse_utils import format_sse
from core.utils.message_utils import extract_node_content
from db.redis_client import redis_async
from services.memory_service import absorb_memory_pipeline


async def run_graph_worker(
    prompt: str,
    thread_id: str,
    user_id: int,
    channel: str,
    lock_key: str,
    user_code: str = "",
) -> None:
    """后台 Worker：执行 LangGraph 推演，将 SSE 事件发布到 Redis Pub/Sub。

    Args:
        prompt: 用户输入。
        thread_id: 会话 UUID（也是 checkpoint thread_id）。
        user_id: 用户 ID（int）。
        channel: Redis Pub/Sub 频道名。
        lock_key: 分布式锁的 Redis Key。
        user_code: 诊断模式下用户提供的待调试代码（可选）。
    """
    await asyncio.sleep(0.1)
    try:
        config = {"configurable": {"thread_id": thread_id}}

        # ---- 判断首轮 / 续轮 ----
        existing = await main_graph.app.aget_state(config)
        has_history = (
            existing is not None
            and existing.values
            and existing.values.get("messages")
        )

        # ---- 组装消息：user_code 作为带标记的 HumanMessage 插入 prompt 之前 ----
        # 目的：user_code 成为 messages 中的一等公民，被 checkpoint 永久持久化，
        # 后续上传不会覆盖历史代码，所有 trimmer 均不受影响。
        msgs = [HumanMessage(content=prompt)]
        if user_code:
            msgs.insert(
                0,
                HumanMessage(
                    content=f"[用户上传了代码]\n```python\n{user_code}\n```",
                    name="code_upload",
                ),
            )

        if has_history:
            input_state = {"messages": msgs}
            input_state["user_id"] = user_id
        else:
            input_state: DevState = {
                "messages": msgs,
                "user_id": user_id,
                "problem_description": prompt,
                "user_code": user_code,
                "algorithm_strategy": "",
                "edge_cases": "",
                "generated_code": "",
                "execution_feedback": "",
                "final_explanation": "",
                "retry_count": 0,
                "mode": "",
                "current_topic": None,
                "user_memory_context": "",
                "diagnose_report": "",
            }

        await redis_async.publish(
            channel,
            format_sse({"node": "system", "content": "DevSwarm 流水线已启动..."}),
        )

        # ---- 跑图 ----
        async for chunk in main_graph.app.astream(input_state, config=config):
            node_name: str = list(chunk.keys())[0]
            node_output: dict = chunk[node_name]

            if node_name.endswith("_tools") or node_name in SKIP_NODES:
                continue

            content: str = extract_node_content(node_name, node_output)
            display_name = NODE_DISPLAY_MAP.get(node_name, node_name)

            await redis_async.publish(
                channel,
                format_sse({"node": display_name, "content": content}),
            )

        await redis_async.publish(
            channel,
            format_sse({"node": "done", "content": "DevSwarm 流水线执行完成。"}),
        )

        # ---- 提前发 EOF，让前端立刻结束 Loading ----
        try:
            await redis_async.publish(channel, EOF_MARKER)
        except Exception:
            pass

        # ---- 在锁保持期间从容进行记忆吸收 ----
        await absorb_memory_pipeline(user_id=user_id, thread_id=thread_id)

    except Exception as exc:
        error_msg = (
            f"服务器执行异常: {type(exc).__name__}: {exc}\n"
            f"```\n{traceback.format_exc()}\n```"
        )
        try:
            await redis_async.publish(
                channel,
                format_sse({"node": "error", "content": error_msg}, event="error"),
            )
        except Exception:
            pass

    finally:
        # ---- 兜底：发布 EOF + 释放分布式锁 ----
        try:
            await redis_async.publish(channel, EOF_MARKER)
        except Exception:
            pass
        try:
            await redis_async.delete(lock_key)
        except Exception:
            pass


async def sse_consumer(channel: str, lock_key: str) -> AsyncGenerator[str, None]:
    """SSE 消费者：订阅 Redis Pub/Sub 频道，将消息透传给前端。

    作为 StreamingResponse 的 body_iterator，生命周期与 HTTP 响应绑定。
    客户端断开 → 协程取消 → finally 执行退订和清理。

    Args:
        channel: Redis Pub/Sub 频道名。
        lock_key: 分布式锁的 Redis Key（仅在异常时兜底释放）。

    Yields:
        SSE 格式字符串（包含结尾换行符）。
    """
    pubsub: Optional[aioredis.client.PubSub] = None
    try:
        pubsub = redis_async.pubsub()
        await pubsub.subscribe(channel)

        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue

            payload: str = msg["data"]
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")

            if payload == EOF_MARKER:
                break

            yield payload

    except Exception:
        # 客户端断开 / 网络异常 → 静默退出
        pass

    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                pass
            try:
                await pubsub.close()
            except Exception:
                pass

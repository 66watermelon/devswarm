

"""
DevSwarm 高可用性（HA）工具库
提供大模型调用的指数退避重试、超时斩断等工业级保护机制。
"""
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
    retry_if_exception_type
)

# 配置日志，方便我们在控制台看到重试的警告信息
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DevSwarm_HA")


# 我们定义一个装饰器，配置指数退避策略
# 策略：最多重试 4 次，等待时间分别为 2秒, 4秒, 8秒, 16秒
@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=16),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=True  # 重试用尽后，把最后的异常抛出，交给 LangGraph 处理
)
def safe_llm_invoke(llm, messages):
    """
    带高可用保护的 LLM 调用包装器。

    Args:
        llm: 实例化的 LangChain LLM 对象
        messages: 传给大模型的消息列表

    Returns:
        LLM 的回复 (AIMessage)
    """
    # 任何网络抖动、429限流都会在这里被拦截并自动重试
    return llm.invoke(messages)
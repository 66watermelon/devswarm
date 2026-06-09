# core/utils/graph_injector.py
import logging
from typing import Optional
from db.graph_reader import GraphReader
from core.prompts.graph_memory_injector import GRAPH_MEMORY_INJECTION_PROMPT

logger = logging.getLogger(__name__)


async def get_graph_memory_prompt(user_id: Optional[str]) -> str:
    """
    获取图谱记忆，并包装成 Prompt 附加块。
    不干扰原有的人设，只作为“潜意识”注入。
    """
    if not user_id:
        return ""

    try:
        memory_context = await GraphReader.get_user_memory_context(str(user_id))
    except Exception as e:
        logger.error(f"⚠️ [GraphInjector] 读取图谱记忆失败: {e}", exc_info=True)
        return ""

    if not memory_context:
        return ""
    
    return GRAPH_MEMORY_INJECTION_PROMPT.format(memory_context=memory_context)
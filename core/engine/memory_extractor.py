import logging
from typing import List
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import BaseMessage

# 1. 引入工厂中的 LLM 实例
from core.engine.llm_factory import llm_extractor
# 2. 引入独立管理的 Prompt
from core.prompts.memory_extractor_prompt import MEMORY_EXTRACTOR_SYSTEM_PROMPT
# 3. 引入数据提取模具
from schemas.graph_memory import ExtractedGraphMemory

logger = logging.getLogger(__name__)


class MemoryExtractorService:
    def __init__(self):
        # 魔法所在：为工厂里的 LLM 套上 Pydantic 模具约束
        self.structured_llm = llm_extractor.with_structured_output(ExtractedGraphMemory)

        # 组装 Prompt（从外部引入，保持业务代码极度干净）
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", MEMORY_EXTRACTOR_SYSTEM_PROMPT),
            ("user", "以下是本轮的对话记录：\n\n{chat_history}")
        ])

        # 组装出纯异步抽取流水线
        self.extractor_chain = self.prompt | self.structured_llm

    async def extract_from_history(self, chat_messages: List[BaseMessage]) -> ExtractedGraphMemory:
        """
        供外部调用的主入口。传入这轮聊天的消息列表，返回强类型的 Pydantic 对象。
        """

        # 将消息列表转化为大模型易读的对话剧本格式
        history_text = "\n".join(
            [f"{'User' if msg.type == 'human' else 'Tutor'}: {msg.content}" for msg in chat_messages]
        )

        try:
            extracted_data: ExtractedGraphMemory = await self.extractor_chain.ainvoke({"chat_history": history_text})

            return extracted_data

        except Exception as e:
            logger.error(f"[MemoryExtractor] 数据提取彻底失败（已超出重试上限）: {e}")
            # 严重失败时返回兜底对象，防止引发级联雪崩
            from schemas.graph_memory import UserState
            return ExtractedGraphMemory(
                concepts=[],
                assessments=[],
                user_state=UserState(frustration_level=1, bad_code_smells=[])
            )
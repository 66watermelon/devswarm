"""
测试 4 种上下文窗口修剪器
"""

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from core.utils.memory_utils import (
    trim_for_intent_recognizer,
    trim_for_chat_agents,
    trim_for_developer,
    trim_for_qa,
)
from tests.conftest import make_human_messages


class TestTrimForIntentRecognizer:

    def test_only_keeps_last_user_message(self):
        msgs = make_human_messages("第一轮", "第二轮", "第三轮")
        result = trim_for_intent_recognizer(msgs)
        assert len(result) == 1
        assert result[0].content == "第三轮"

    def test_empty_returns_empty(self):
        assert trim_for_intent_recognizer([]) == []

    def test_skips_ai_messages(self):
        msgs = [HumanMessage(content="提问"), AIMessage(content="回答", name="analyst")]
        result = trim_for_intent_recognizer(msgs)
        assert result[0].content == "提问"


class TestTrimForChatAgents:

    def test_keeps_system_prompt(self):
        msgs = [SystemMessage(content="sys"), HumanMessage(content="user")]
        result = trim_for_chat_agents(msgs, {"analyst"}, keep_rounds=2)
        assert any(isinstance(m, SystemMessage) for m in result)

    def test_filters_developer_and_qa(self):
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="user"),
            AIMessage(content="dev", name="developer"),
            AIMessage(content="qa", name="qa"),
            AIMessage(content="analyst", name="analyst"),
        ]
        result = trim_for_chat_agents(msgs, {"analyst"}, keep_rounds=2)
        names = [getattr(m, "name", "") for m in result if isinstance(m, AIMessage)]
        assert "developer" not in names
        assert "qa" not in names
        assert "analyst" in names

    def test_sliding_window_truncates_old_rounds(self):
        msgs = [SystemMessage(content="sys")]
        for i in range(5):
            msgs.append(HumanMessage(content=f"user_{i}"))
            msgs.append(AIMessage(content=f"analyst_{i}", name="analyst"))
        result = trim_for_chat_agents(msgs, {"analyst"}, keep_rounds=2)
        chat = [m for m in result if not isinstance(m, SystemMessage)]
        assert len(chat) <= 5  # max = 2*2+1

    def test_filters_tool_messages(self):
        msgs = [
            SystemMessage(content="sys"), HumanMessage(content="user"),
            ToolMessage(content="sandbox", tool_call_id="1"),
            AIMessage(content="ok", name="analyst"),
        ]
        result = trim_for_chat_agents(msgs, {"analyst"}, keep_rounds=2)
        assert not any(isinstance(m, ToolMessage) for m in result)

    def test_code_upload_human_message_is_kept(self):
        """code_upload HumanMessage 应被保留（HumanMessage 类别）。"""
        msgs = [
            HumanMessage(content="def foo(): pass", name="code_upload"),
            HumanMessage(content="这段代码为什么错"),
        ]
        result = trim_for_chat_agents(msgs, {"analyst"}, keep_rounds=2)
        assert len([m for m in result if isinstance(m, HumanMessage)]) == 2


class TestTrimForDeveloper:

    def test_system_plus_latest_qa(self):
        msgs = [
            SystemMessage(content="sys"), HumanMessage(content="user"),
            AIMessage(content="err", name="qa"),
        ]
        result = trim_for_developer(msgs)
        has_sys = any(isinstance(m, SystemMessage) for m in result)
        has_qa = any(getattr(m, "name", "") == "qa" for m in result)
        assert has_sys and has_qa

    def test_no_qa_returns_only_system(self):
        msgs = [SystemMessage(content="sys"), HumanMessage(content="user")]
        result = trim_for_developer(msgs)
        assert len(result) == 1
        assert isinstance(result[0], SystemMessage)

    def test_strips_human_messages(self):
        msgs = [
            SystemMessage(content="sys"), HumanMessage(content="u1"),
            AIMessage(content="e", name="qa"), HumanMessage(content="u2"),
        ]
        result = trim_for_developer(msgs)
        assert not any(isinstance(m, HumanMessage) for m in result)


class TestTrimForQA:

    def test_cuts_before_last_developer(self):
        msgs = [
            HumanMessage(content="old"),
            AIMessage(content="code", name="developer"),
            AIMessage(content="call", name="qa"),
            ToolMessage(content="result", tool_call_id="1"),
        ]
        result = trim_for_qa(msgs)
        assert len(result) == 3

    def test_no_developer_falls_back_to_last_user(self):
        msgs = [
            HumanMessage(content="u1"),
            AIMessage(content="a", name="analyst"),
            HumanMessage(content="u2"),
        ]
        result = trim_for_qa(msgs)
        assert len(result) == 1
        assert result[0].content == "u2"

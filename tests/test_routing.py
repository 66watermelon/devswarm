"""
测试 4 个路由函数 + SSE 格式化
"""

import json
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage

from main_graph import (
    route_after_intent,
    route_after_analysis,
    route_after_developer,
    route_after_qa,
)
from core.utils.sse_utils import format_sse
from tests.conftest import build_test_state


# ================================================================
# 路由测试
# ================================================================

class TestRouteAfterIntent:
    def test_solve_to_analyst(self):
        assert route_after_intent(build_test_state(mode="solve")) == "analyst"
    def test_diagnose_to_analyst(self):
        assert route_after_intent(build_test_state(mode="diagnose")) == "analyst"
    def test_chat_to_chat_agent(self):
        assert route_after_intent(build_test_state(mode="chat")) == "chat_agent"
    def test_default_is_analyst(self):
        assert route_after_intent(build_test_state(mode="")) == "analyst"


class TestRouteAfterAnalysis:
    def test_solve_to_developer(self):
        assert route_after_analysis(build_test_state(mode="solve")) == "developer"
    def test_diagnose_to_qa(self):
        assert route_after_analysis(build_test_state(mode="diagnose")) == "qa"


class TestRouteAfterDeveloper:
    def test_tool_call_goes_to_tools(self):
        msg = MagicMock()
        msg.tool_calls = [{"name": "write"}]
        assert route_after_developer(build_test_state(messages=[msg])) == "developer_tools"
    def test_no_tool_goes_to_qa(self):
        assert route_after_developer(build_test_state()) == "qa"


class TestRouteAfterQA:

    # ---- solve ----
    def test_solve_pass_to_tutor(self):
        s = build_test_state(mode="solve", execution_feedback="")
        assert route_after_qa(s) == "tutor"

    def test_solve_fail_retry_to_developer(self):
        s = build_test_state(mode="solve", execution_feedback="err", retry_count=1)
        assert route_after_qa(s) == "developer"

    def test_solve_meltdown_to_tutor(self):
        s = build_test_state(mode="solve", execution_feedback="err", retry_count=3)
        assert route_after_qa(s) == "tutor"

    # ---- diagnose ----
    def test_diagnose_pass_to_chat_agent(self):
        s = build_test_state(mode="diagnose", execution_feedback="")
        assert route_after_qa(s) == "chat_agent"

    def test_diagnose_fail_retry_to_developer(self):
        s = build_test_state(mode="diagnose", execution_feedback="err", retry_count=2)
        assert route_after_qa(s) == "developer"

    def test_diagnose_meltdown_to_chat_agent(self):
        s = build_test_state(mode="diagnose", execution_feedback="err", retry_count=3)
        assert route_after_qa(s) == "chat_agent"

    # ---- tool_calls 优先 ----
    def test_tool_calls_take_priority(self):
        msg = MagicMock()
        msg.tool_calls = [{"name": "run_sandbox"}]
        s = build_test_state(messages=[msg], execution_feedback="err", retry_count=5)
        assert route_after_qa(s) == "qa_tools"


# ================================================================
# SSE 测试
# ================================================================

class TestFormatSSE:
    def test_basic(self):
        r = format_sse({"node": "analyst", "content": "test"})
        assert r.startswith("data: ") and r.endswith("\n\n")

    def test_with_event(self):
        r = format_sse({"node": "error", "content": "msg"}, event="error")
        assert r.startswith("event: error\n")

    def test_unicode(self):
        r = format_sse({"node": "system", "content": "中文"})
        assert "中文" in r

    def test_newline_escaped(self):
        r = format_sse({"content": "line1\nline2"})
        parsed = json.loads(r[6:-2])
        assert parsed["content"] == "line1\nline2"

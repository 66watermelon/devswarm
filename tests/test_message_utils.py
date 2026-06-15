"""
测试消息清洗 + 节点内容提取
"""

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from core.utils.message_utils import clean_messages, extract_node_content


class TestCleanMessages:

    def test_user_kept(self):
        assert clean_messages([HumanMessage(content="你好")]) == [
            {"role": "user", "content": "你好"}
        ]

    def test_analyst_kept(self):
        assert clean_messages([AIMessage(content="分析", name="analyst")]) == [
            {"role": "analyst", "content": "分析"}
        ]

    def test_tutor_kept(self):
        assert clean_messages([AIMessage(content="题解", name="tutor")]) == [
            {"role": "tutor", "content": "题解"}
        ]

    def test_developer_filtered(self):
        assert clean_messages([AIMessage(content="def x", name="developer")]) == []

    def test_qa_filtered(self):
        assert clean_messages([AIMessage(content="fail", name="qa")]) == []

    def test_tool_message_filtered(self):
        assert clean_messages([ToolMessage(content="out", tool_call_id="1")]) == []

    def test_unnamed_aimessage_filtered(self):
        assert clean_messages([AIMessage(content="?")]) == []

    def test_empty_content_filtered(self):
        assert clean_messages([AIMessage(content="", name="analyst")]) == []

    def test_mixed_messages_correct_order(self):
        msgs = [
            HumanMessage(content="问"),
            AIMessage(content="策", name="analyst"),
            AIMessage(content="码", name="developer"),
            AIMessage(content="解", name="tutor"),
            ToolMessage(content="工具", tool_call_id="1"),
        ]
        result = clean_messages(msgs)
        assert len(result) == 3
        assert [m["role"] for m in result] == ["user", "analyst", "tutor"]

    def test_multimodal_extracts_text_only(self):
        msgs = [AIMessage(
            content=[
                {"type": "text", "text": "A"},
                {"type": "image_url", "image_url": {"url": "http://x"}},
                {"type": "text", "text": "B"},
            ],
            name="analyst",
        )]
        assert clean_messages(msgs)[0]["content"] == "A\nB"


class TestExtractNodeContent:

    def test_analyst_merges_strategy_and_edge(self):
        out = {"algorithm_strategy": "O(n)", "edge_cases": "空数组", "messages": []}
        content = extract_node_content("analyst", out)
        assert "O(n)" in content and "空数组" in content

    def test_developer_reads_last_aimessage(self):
        out = {"messages": [AIMessage(content="old"), AIMessage(content="new")]}
        assert extract_node_content("developer", out) == "new"

    def test_qa_pass(self):
        out = {"execution_feedback": ""}
        assert "通过" in extract_node_content("qa", out)

    def test_qa_fail(self):
        out = {"execution_feedback": "IndexError"}
        assert "失败" in extract_node_content("qa", out)

    def test_tutor_reads_final_explanation(self):
        out = {"final_explanation": "# 题解\n内容"}
        assert extract_node_content("tutor", out) == "# 题解\n内容"

    def test_tools_truncates(self):
        out = {"messages": [ToolMessage(content="x" * 500, tool_call_id=str(i)) for i in range(5)]}
        content = extract_node_content("developer_tools", out)
        assert len(content) < 1000  # 前3条 × 300字截断

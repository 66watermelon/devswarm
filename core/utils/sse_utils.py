"""
DevSwarm SSE 格式化工具

提供符合 Server-Sent Events 协议的单行 JSON 编码输出。
"""

import json
from typing import Optional


def format_sse(data: dict, event: Optional[str] = None) -> str:
    """将字典格式化为严格的 SSE 协议字符串。

    json.dumps 会自动将换行符转义为 \\n，保证单行输出，完全符合 SSE 规范。

    Args:
        data: 要发送的字典，会被 JSON 序列化。
        event: 可选的事件类型名称（如 "error"）。

    Returns:
        符合 SSE 协议格式的字符串（以两个换行符结尾）。
    """
    result = ""
    if event:
        result += f"event: {event}\n"
    result += f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    return result

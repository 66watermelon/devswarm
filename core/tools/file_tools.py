"""
文件管理工具集 —— 所有操作被严格锁定在 workspace 目录内。

提供给 LangGraph AI Agent 的三个工具函数：
- read_workspace_file:  读取文件内容
- write_workspace_file: 写入文件（自动创建父目录）
- list_workspace_files: 列出目录内容

安全模型：
    基于 Path.resolve() 的路径穿越（Path Traversal）防御。任何试图通过 ../ 或
    绝对路径逃逸出 workspace 目录的操作都会被拒绝并返回 PermissionError。
"""

import os
from pathlib import Path

from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# 工作区根目录
# ---------------------------------------------------------------------------
# 可通过环境变量 WORKSPACE_ROOT 覆盖；默认取 tools/ 同级目录下的 workspace/
_WORKSPACE_ROOT = Path(
    os.environ.get(
        "WORKSPACE_ROOT",
        str(Path(__file__).resolve().parent.parent.parent / "workspace"),
    )
).resolve()

# 确保工作区根目录存在
_WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 内部安全函数
# ---------------------------------------------------------------------------

def _resolve_safe(relative_path: str) -> Path:
    """
    安全地将用户输入的相对路径解析为 workspace 内的绝对路径，
    并验证最终路径没有逃逸出 workspace 目录。

    防御策略：
        1. 将用户路径拼接到 workspace 根目录。
        2. 调用 .resolve() 消除所有 .. 和符号链接，得到真实规范路径。
        3. 使用 Path.is_relative_to() 检查规范路径是否仍在 workspace 内。

    Args:
        relative_path: 用户（LLM）提供的相对路径字符串。

    Returns:
        解析后的绝对 Path 对象，保证位于 _WORKSPACE_ROOT 之内。

    Raises:
        PermissionError: 如果解析后的路径逃逸出 workspace 目录。
    """
    # 拼接用户路径并解析为规范路径
    candidate = (_WORKSPACE_ROOT / relative_path).resolve()

    # 安全检查：候选路径必须是 workspace 的子路径或等于 workspace
    try:
        candidate.relative_to(_WORKSPACE_ROOT)
    except ValueError:
        raise PermissionError(
            f"Path traversal blocked: '{relative_path}' resolves to "
            f"'{candidate}', which is outside the allowed workspace "
            f"'{_WORKSPACE_ROOT}'."
        )

    return candidate


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

@tool
def read_workspace_file(relative_path: str) -> str:
    """
    读取 workspace 目录下的文件内容并返回全文。

    使用此工具读取工作区中的任何文本文件。提供相对于 workspace 根目录的文件路径。
    示例: read_workspace_file("notes.txt")
    示例: read_workspace_file("reports/summary.md")

    Args:
        relative_path: 文件相对于 workspace 根目录的路径，如 "data.json"。

    Returns:
        文件的完整文本内容。如果文件不存在或发生错误，返回描述性的错误字符串。
    """
    try:
        target = _resolve_safe(relative_path)

        if not target.exists():
            return (
                f"Error: File not found — '{relative_path}' does not exist "
                f"in the workspace."
            )
        if not target.is_file():
            return (
                f"Error: '{relative_path}' is not a file. "
                f"Use list_workspace_files() to browse the directory structure."
            )

        return target.read_text(encoding="utf-8")

    except PermissionError:
        return (
            f"Permission denied: '{relative_path}' is outside the allowed "
            f"workspace directory. Only paths within the workspace are accessible."
        )
    except UnicodeDecodeError:
        return (
            f"Error: '{relative_path}' cannot be decoded as UTF-8 text. "
            f"It may be a binary file."
        )
    except OSError as exc:
        return f"Error reading '{relative_path}': {exc}"


@tool
def write_workspace_file(relative_path: str, content: str) -> str:
    """
    将文本内容写入 workspace 目录下的文件（创建新文件或覆盖已有文件）。

    使用此工具创建或更新工作区中的文件。如果目标路径的父目录不存在，会自动创建。
    示例: write_workspace_file("output/result.json", '{"score": 95}')

    Args:
        relative_path: 文件相对于 workspace 根目录的路径，如 "output/script.py"。
        content: 要写入文件的完整文本内容。

    Returns:
        操作结果的成功或失败消息字符串。
    """
    try:
        target = _resolve_safe(relative_path)

        # 自动创建父目录（等价于 os.makedirs）
        target.parent.mkdir(parents=True, exist_ok=True)

        target.write_text(content, encoding="utf-8")
        return (
            f"Successfully wrote {len(content)} characters to "
            f"'{relative_path}'."
        )

    except PermissionError:
        return (
            f"Permission denied: '{relative_path}' is outside the allowed "
            f"workspace directory. Only paths within the workspace are writable."
        )
    except OSError as exc:
        return f"Error writing '{relative_path}': {exc}"


@tool
def list_workspace_files(relative_dir: str = ".") -> str:
    """
    列出 workspace 目录下指定路径的文件和子目录。

    使用此工具浏览工作区中的目录结构，了解有哪些文件可用。
    示例: list_workspace_files(".") 列出根目录
    示例: list_workspace_files("data") 列出 data 子目录

    Args:
        relative_dir: 相对于 workspace 根目录的目录路径，默认为 "."（根目录）。

    Returns:
        格式化后的文件与目录列表字符串，每行一项，用 [FILE] / [DIR] 标记类型。
    """
    try:
        target = _resolve_safe(relative_dir)

        if not target.exists():
            return (
                f"Error: Directory not found — '{relative_dir}' does not exist "
                f"in the workspace."
            )
        if not target.is_dir():
            return (
                f"Error: '{relative_dir}' is not a directory. "
                f"Use read_workspace_file() to read a file."
            )

        entries = sorted(target.iterdir())
        if not entries:
            return f"Directory '{relative_dir}' is empty."

        lines = [f"Contents of '{relative_dir}' ({len(entries)} items):"]
        for entry in entries:
            tag = "DIR " if entry.is_dir() else "FILE"
            display = str(entry.relative_to(_WORKSPACE_ROOT))
            lines.append(f"  [{tag}] {display}")

        return "\n".join(lines)

    except PermissionError:
        return (
            f"Permission denied: '{relative_dir}' is outside the allowed "
            f"workspace directory. Only paths within the workspace are accessible."
        )
    except OSError as exc:
        return f"Error listing '{relative_dir}': {exc}"

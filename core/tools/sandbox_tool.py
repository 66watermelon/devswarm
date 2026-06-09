"""
DevSwarm V2 沙箱测试工具

提供给 QA Agent 在 Docker 沙箱中执行任意命令的能力。

V1 → V2 核心变化：
- 入参从 code_string（代码字符串）变为 command（Shell 命令）
- 不再需要 QA 自己去读代码内容再传进来
- QA 只需告诉沙箱"执行什么命令"，沙箱会自动挂载整个 workspace 目录并运行

工作原理：
1. QA 传入命令（如 "python main.py" 或 "pytest tests/ -v"）
2. 工具将 workspace 目录完整拷贝到宿主机临时目录（物理隔离）
3. Docker 容器以读写方式挂载该临时目录到 /app
4. 在容器内执行命令
5. 执行完毕后销毁容器和临时目录，返回结果报告
6. 原始 workspace 文件不受任何影响
"""

from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

from core.engine.sandbox import (
    Sandbox,
    SandboxResult,
    run_sandbox_sync,
)
from core.engine.exceptions import (
    SandboxExecutionError,
    SandboxTimeoutError,
    SandboxError,
)
# _WORKSPACE_ROOT 指向项目根目录下的 workspace/ 文件夹
# Developer 写入的所有代码文件都在这里，沙箱将其挂载为 /app 后执行命令
from core.tools.file_tools import _WORKSPACE_ROOT


# ---------------------------------------------------------------------------
# 结果格式化
# ---------------------------------------------------------------------------

def _format_sandbox_report(result: SandboxResult) -> str:
    """将 SandboxResult 格式化为 LLM 可读的结构化文本报告。

    报告包含四个部分：
    1. Exit Code —— 程序退出码（0=成功）
    2. Status   —— 人类可读的执行状态（SUCCESS / FAILED / TIMED OUT）
    3. STDOUT   —— 标准输出（程序正常运行时的打印内容）
    4. STDERR   —— 标准错误（报错信息、异常堆栈等）

    Args:
        result: 沙箱执行返回的 SandboxResult 对象。

    Returns:
        格式化后的多行纯文本字符串，可直接展示给 LLM。
    """
    lines: list[str] = []

    # ---- 退出码 ----
    lines.append(f"Exit Code: {result.exit_code}")

    # ---- 执行状态 ----
    if result.is_timeout:
        lines.append(
            f"Status: [FAILED] Execution TIMED OUT "
            f"(exceeded {Sandbox.EXEC_TIMEOUT:.0f} seconds)."
        )
    elif result.exit_code == 0:
        lines.append("Status: [SUCCESS] Execution completed normally.")
    else:
        lines.append(
            f"Status: [FAILED] Execution terminated with exit code {result.exit_code}."
        )

    # ---- 标准输出 ----
    lines.append("\n--- STDOUT ---")
    lines.append(result.stdout if result.stdout.strip() else "(empty)")

    # ---- 标准错误 ----
    lines.append("\n--- STDERR ---")
    lines.append(result.stderr if result.stderr.strip() else "(empty)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 定义
# ---------------------------------------------------------------------------

@tool
def run_sandbox_test(
    command: str,
    timeout: Optional[float] = None,
) -> str:
    """在隔离的 Docker 沙箱中执行终端命令，并返回完整的执行结果报告。

    【重要】你不需要传递代码字符串！
    Developer 已经将代码文件写入了 workspace 工作区。
    你只需要告诉沙箱"如何运行"这些代码即可。

    工作原理：
    - 整个 workspace 目录会被自动挂载到容器的 /app 目录
    - 命令以 /app 为工作目录执行
    - 你可以使用相对路径引用 workspace 中的任何文件

    使用示例:
        run_sandbox_test("python main.py")              # 运行单个脚本
        run_sandbox_test("pytest tests/ -v")            # 运行 pytest 测试套件
        run_sandbox_test("python -m unittest discover")  # 运行 unittest 测试发现
        run_sandbox_test("bash scripts/test.sh")        # 运行自定义测试脚本

    Args:
        command: 要在沙箱中执行的 Shell 命令。
                 支持管道 (|)、重定向 (>、<) 等标准 Shell 语法。
        timeout: 可选，自定义超时时间（秒）。不传则使用默认的 30 秒。

    Returns:
        结构化文本报告，包含：
        - Exit Code（退出码，0 表示成功）
        - Status（SUCCESS / FAILED / TIMED OUT）
        - STDOUT（标准输出内容）
        - STDERR（标准错误内容，包含报错信息和异常堆栈）
    """
    # ---- 第 1 步：确认 workspace 存在且非空 ----
    # 如果 workspace 不存在或为空，说明 Developer 还没有写入任何代码。
    # 此时不应启动沙箱（会浪费资源），直接返回明确的错误提示。
    workspace_dir: Path = _WORKSPACE_ROOT

    if not workspace_dir.exists():
        return (
            f"Error: Workspace directory does not exist: '{workspace_dir}'. "
            f"Developer must create code files first before QA can run tests."
        )

    if not any(workspace_dir.iterdir()):
        return (
            f"Error: Workspace directory is empty. "
            f"Developer has not written any code files yet. "
            f"Use list_workspace_files() to check what files exist."
        )

    # ---- 第 2 步：调用新版沙箱引擎执行命令 ----
    # run_sandbox_sync 会自动：
    #   1. 将 workspace_dir 拷贝到宿主机临时目录（物理隔离）
    #   2. 启动 Docker 容器并挂载临时目录到 /app
    #   3. 在容器内执行 command
    #   4. 销毁容器并清理临时目录
    #   5. 返回 SandboxResult 或抛出 SandboxError 子类异常
    try:
        result: SandboxResult = run_sandbox_sync(
            command=command,
            source_dir=workspace_dir,
            timeout=timeout,
        )
        # 正常情况下走到这里说明 exit_code == 0 且未超时
        return _format_sandbox_report(result)

    # ---- 第 3 步：异常兜底，转化为 LLM 可读的错误字符串 ----
    # 注意：这里不向上抛异常，而是返回友好的错误描述。
    # LangChain Tool 的返回值会直接展示给 LLM，所以必须是纯文本。

    except SandboxTimeoutError:
        # 命令执行超过时间限制被强制 kill
        return (
            f"Status: [TIMEOUT] Command '{command}' exceeded the "
            f"{Sandbox.EXEC_TIMEOUT:.0f}s time limit and was killed.\n"
            f"Possible causes: infinite loop, blocking I/O, or overly complex computation.\n"
            f"Suggestion: ask Developer to optimize the code or add progress checkpoints."
        )

    except SandboxExecutionError as exc:
        # 命令执行完毕但返回了非零退出码（程序崩溃、测试失败等）
        return (
            f"Status: [FAILED] Command exited with code {exc.exit_code}.\n"
            f"--- STDOUT ---\n{exc.stdout or '(empty)'}\n"
            f"--- STDERR ---\n{exc.stderr or '(empty)'}"
        )

    except SandboxError as exc:
        # Docker 环境或文件系统层面的错误（镜像拉取失败、磁盘满等）
        return (
            f"Status: [ERROR] Sandbox infrastructure error: {exc.message}\n"
            f"This is not a code bug — the sandbox environment itself has a problem."
        )

    except Exception as exc:
        # 完全未预期的异常，兜底返回
        return f"Status: [ERROR] Unexpected sandbox failure: {exc}"

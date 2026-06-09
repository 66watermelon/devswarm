"""
DevSwarm 统一异常体系

所有自定义异常继承自 DevSwarmError 基类，便于上层统一捕获。
严禁直接抛出裸的 Exception 或使用泛化的 try/except 吞掉错误。

异常层级：
    DevSwarmError
    ├── ConfigError              配置错误（API Key 缺失等）
    ├── SandboxError             沙箱执行相关错误
    │   ├── SandboxExecutionError    代码执行失败（非零退出码）
    │   ├── SandboxTimeoutError      执行超时
    │   └── SandboxResourceError     资源不足（内存/CPU/磁盘）
    ├── LLMError                 LLM 调用相关错误
    │   ├── LLMGenerationError       LLM 生成失败
    │   └── LLMToolCallError         Tool Call 异常
    └── WorkspaceError           工作区文件操作错误
        ├── WorkspaceAccessError    路径越界 / 权限拒绝
        └── WorkspaceNotFoundError  文件或目录不存在
"""

from typing import Optional


class DevSwarmError(Exception):
    """DevSwarm 平台所有自定义异常的基类。

    Attributes:
        message: 人类可读的错误描述。
        details: 可选的附加诊断信息字典。
    """

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.message: str = message
        self.details: Optional[dict] = details or {}

    def __str__(self) -> str:
        base = f"[{self.__class__.__name__}] {self.message}"
        if self.details:
            base += f" (details={self.details})"
        return base


# ---------------------------------------------------------------------------
# 配置错误
# ---------------------------------------------------------------------------

class ConfigError(DevSwarmError):
    """配置相关错误。

    例如：API Key 未设置、Base URL 格式错误、必需的 .env 字段缺失。
    """
    pass


# ---------------------------------------------------------------------------
# 沙箱错误
# ---------------------------------------------------------------------------

class SandboxError(DevSwarmError):
    """沙箱执行相关错误的基类。"""
    pass


class SandboxExecutionError(SandboxError):
    """沙箱中代码执行失败（非零退出码）。

    Attributes:
        exit_code: 容器退出码。
        stdout: 标准输出内容。
        stderr: 标准错误输出内容。
    """

    def __init__(
        self,
        message: str,
        exit_code: int = -1,
        stdout: str = "",
        stderr: str = "",
        details: Optional[dict] = None,
    ) -> None:
        super().__init__(message, details)
        self.exit_code: int = exit_code
        self.stdout: str = stdout
        self.stderr: str = stderr


class SandboxTimeoutError(SandboxError):
    """沙箱执行超时。

    Attributes:
        timeout_seconds: 配置的超时阈值（秒）。
    """

    def __init__(
        self,
        message: str,
        timeout_seconds: float = 0.0,
        details: Optional[dict] = None,
    ) -> None:
        super().__init__(message, details)
        self.timeout_seconds: float = timeout_seconds


class SandboxResourceError(SandboxError):
    """沙箱资源不足（内存溢出、磁盘满等）。"""
    pass


# ---------------------------------------------------------------------------
# LLM 错误
# ---------------------------------------------------------------------------

class LLMError(DevSwarmError):
    """LLM 调用相关错误的基类。"""
    pass


class LLMGenerationError(LLMError):
    """LLM 文本生成失败。

    可能原因：API 限流、模型不可用、Token 超限、响应格式异常。
    """
    pass


class LLMToolCallError(LLMError):
    """LLM 的 Tool Call 执行异常。

    可能原因：工具返回格式不符合预期、工具执行过程中抛出未捕获异常。
    """
    pass


# ---------------------------------------------------------------------------
# 工作区错误
# ---------------------------------------------------------------------------

class WorkspaceError(DevSwarmError):
    """工作区文件操作错误的基类。"""
    pass


class WorkspaceAccessError(WorkspaceError):
    """工作区访问被拒绝（路径穿越攻击、权限不足）。

    Attributes:
        path: 被拒绝访问的路径。
    """

    def __init__(
        self,
        message: str,
        path: str = "",
        details: Optional[dict] = None,
    ) -> None:
        super().__init__(message, details)
        self.path: str = path


class WorkspaceNotFoundError(WorkspaceError):
    """工作区文件或目录不存在。

    Attributes:
        path: 未找到的路径。
    """

    def __init__(
        self,
        message: str,
        path: str = "",
        details: Optional[dict] = None,
    ) -> None:
        super().__init__(message, details)
        self.path: str = path

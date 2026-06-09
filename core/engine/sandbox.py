"""
DevSwarm V2 沙箱执行引擎

基于 Docker 的安全代码执行环境，支持多文件项目。

安全设计（企业级 Hardening）：
- 物理隔离：每次执行前将源代码拷贝到临时目录，挂载副本而非原始工作区
- 用完即毁：执行完毕后强制删除临时目录和容器，零残留
- 内存限制：512MB（可通过 MEM_LIMIT 配置）
- CPU 限制：0.5 核（可通过 CPU_LIMIT 配置）
- 网络隔离：network_mode="none"，完全断网
- 超时控制：30 秒默认，可配置
- 能力裁剪 + no-new-privileges

设计权衡：
- 挂载模式为 rw（读写）：因为 Python/pytest 运行时需要创建 __pycache__、.pytest_cache
  等缓存目录。安全性由"操作副本 + 执行后销毁"保证，而非只读挂载。
- 容器根文件系统不设 read_only：同理，解释器需要写临时文件。

使用示例：
    sandbox = Sandbox()
    result = await sandbox.execute(
        command="pytest tests/ -v",
        source_dir=Path("/path/to/workspace"),
    )
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import docker
from docker.errors import DockerException, ImageNotFound, APIError
from docker.models.containers import Container

from core.engine.exceptions import (
    SandboxError,
    SandboxExecutionError,
    SandboxTimeoutError,
    SandboxResourceError,
)


# ---------------------------------------------------------------------------
# 结果数据类
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SandboxResult:
    """沙箱执行结果（不可变数据类）。

    Attributes:
        exit_code: 容器退出码（0 表示成功）。
        stdout: 标准输出内容。
        stderr: 标准错误输出内容。
        is_timeout: 是否因超时被强制终止。
    """
    exit_code: int
    stdout: str
    stderr: str
    is_timeout: bool = False

    def to_dict(self) -> dict[str, int | str | bool]:
        """将结果转为字典（兼容 V1 接口）。

        Returns:
            dict: 包含 exit_code, stdout, stderr, is_timeout 的字典。
        """
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "is_timeout": self.is_timeout,
        }


# ---------------------------------------------------------------------------
# 沙箱引擎
# ---------------------------------------------------------------------------

class Sandbox:
    """基于 Docker 的隔离代码执行沙箱。

    执行流程：
    1. 将 source_dir 完整拷贝到宿主机临时目录（物理隔离）。
    2. 以读写方式将临时目录 bind mount 到容器内 /app。
    3. 在容器内执行指定命令。
    4. 无论成功/失败/超时，销毁容器并删除临时目录。

    安全模型：
    - 原始工作区绝不暴露给容器（只拷贝副本）
    - 容器断网 + 能力裁剪 + 禁止提权
    - 内存/CPU 硬限制 + 超时强制 kill
    - finally 块保证资源清理

    Attributes:
        IMAGE: Docker 镜像名。
        MEM_LIMIT: 内存上限。
        CPU_LIMIT: CPU 核数上限。
        EXEC_TIMEOUT: 默认执行超时（秒）。
        KILL_GRACE: kill 后等待容器退出的宽限时间（秒）。
    """

    # ---- 沙箱资源限制常量 ----
    IMAGE: str = "python:3.11-slim"
    MEM_LIMIT: str = "512m"
    CPU_LIMIT: float = 0.5
    EXEC_TIMEOUT: float = 30.0
    KILL_GRACE: float = 3.0

    # ---- 容器内固定路径 ----
    APP_DIR: str = "/app"

    def __init__(
        self,
        docker_client: Optional[docker.DockerClient] = None,
    ) -> None:
        """初始化沙箱。

        Args:
            docker_client: 可选，注入已有的 Docker 客户端实例。
                           不传则自动调用 docker.from_env()。
        """
        self._docker: docker.DockerClient = docker_client or docker.from_env()
        self._image_ready: bool = False

    # ------------------------------------------------------------------
    # 镜像管理
    # ------------------------------------------------------------------

    async def _ensure_image(self) -> None:
        """确保 Docker 镜像在本地存在，如不存在则拉取。

        Raises:
            SandboxResourceError: 镜像拉取失败。
        """
        if self._image_ready:
            return
        try:
            await asyncio.to_thread(self._docker.images.get, self.IMAGE)
        except ImageNotFound:
            try:
                await asyncio.to_thread(
                    self._docker.images.pull,
                    self.IMAGE,
                    platform="linux/amd64",
                )
            except DockerException as exc:
                raise SandboxResourceError(
                    f"Failed to pull Docker image '{self.IMAGE}': {exc}",
                    details={"image": self.IMAGE},
                ) from exc
        self._image_ready = True

    # ------------------------------------------------------------------
    # 核心执行方法
    # ------------------------------------------------------------------

    async def execute(
        self,
        command: str | list[str],
        source_dir: Path,
        env: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> SandboxResult:
        """在隔离容器中执行命令。

        执行前将 source_dir 拷贝到宿主机临时目录，以读写方式挂载到容器内 /app。
        执行后无论成功与否，销毁容器并删除临时目录，保证零残留。

        Args:
            command: 要执行的命令。
                     字符串形式: "python main.py"
                     列表形式: ["pytest", "tests/", "-v"]
            source_dir: 宿主机上要挂载的源代码目录（必须存在）。
                        注意：原始目录不会被修改，沙箱操作的是拷贝副本。
            env: 可选的环境变量字典。
            timeout: 可选，覆盖默认超时时间（秒）。

        Returns:
            SandboxResult: 包含退出码、stdout、stderr、超时标记的结果对象。

        Raises:
            SandboxExecutionError: 命令执行返回非零退出码。
            SandboxTimeoutError: 执行超时。
            SandboxError: 其他 Docker 或沙箱层面的错误。
            ValueError: source_dir 不存在或不是目录。
        """
        # ---- 0. 参数校验 ----
        if not source_dir.exists():
            raise ValueError(f"source_dir does not exist: {source_dir}")
        if not source_dir.is_dir():
            raise ValueError(f"source_dir is not a directory: {source_dir}")

        if isinstance(command, list):
            shell_cmd: str = " ".join(command)
            exec_cmd: list[str] = command
        else:
            shell_cmd = command
            exec_cmd = ["sh", "-c", command]

        effective_timeout: float = (
            timeout if timeout is not None else self.EXEC_TIMEOUT
        )

        container: Optional[Container] = None
        sandbox_id: str = uuid.uuid4().hex[:12]
        # 临时目录：在 finally 块中统一清理
        sandbox_dir: Optional[Path] = None

        try:
            # ---- 1. 创建物理隔离的临时目录 ----
            # 将 source_dir 完整拷贝到系统临时目录，容器只操作副本。
            # 原始工作区文件不受任何影响；临时目录在执行后被删除。
            sandbox_dir = Path(
                await asyncio.to_thread(
                    tempfile.mkdtemp,
                    prefix=f"devswarm_{sandbox_id}_",
                )
            )
            await asyncio.to_thread(
                shutil.copytree,
                str(source_dir),
                str(sandbox_dir),
                dirs_exist_ok=True,
            )

            # ---- 2. 确保镜像就绪 ----
            await self._ensure_image()

            # ---- 3. 构建容器运行参数 ----
            # 挂载模式为 rw：Python/pytest 需要创建 __pycache__、.pytest_cache
            # 安全性由"挂载临时副本 + 执行后销毁"保证，而非只读限制。
            run_kwargs: dict = {
                "image": self.IMAGE,
                "command": exec_cmd,
                "volumes": {
                    str(sandbox_dir): {
                        "bind": self.APP_DIR,
                        "mode": "rw",
                    }
                },
                "working_dir": self.APP_DIR,
                "mem_limit": self.MEM_LIMIT,
                "nano_cpus": int(self.CPU_LIMIT * 1_000_000_000),
                "network_mode": "none",
                "detach": True,
                "stdout": True,
                "stderr": True,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
            }

            if env:
                run_kwargs["environment"] = env

            # ---- 4. 启动容器 ----
            container = await asyncio.to_thread(
                self._docker.containers.run,
                **run_kwargs,
            )

            # ---- 5. 等待容器结束，带超时控制 ----
            exit_code: int = -1
            is_timeout: bool = False

            try:
                exit_result = await asyncio.wait_for(
                    asyncio.to_thread(container.wait),
                    timeout=effective_timeout,
                )
                exit_code = exit_result.get("StatusCode", -1)

            except asyncio.TimeoutError:
                is_timeout = True
                exit_code = -1
                # 强制终止容器
                try:
                    await asyncio.to_thread(container.kill)
                except APIError:
                    pass
                # 等待容器真正退出
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(container.wait),
                        timeout=self.KILL_GRACE,
                    )
                except asyncio.TimeoutError:
                    pass

            # ---- 6. 收集日志 ----
            stdout_bytes, stderr_bytes = b"", b""
            try:
                stdout_bytes = await asyncio.to_thread(
                    container.logs, stdout=True, stderr=False
                )
                stderr_bytes = await asyncio.to_thread(
                    container.logs, stdout=False, stderr=True
                )
            except APIError:
                pass

            stdout = (
                stdout_bytes.decode("utf-8", errors="replace")
                if isinstance(stdout_bytes, bytes)
                else str(stdout_bytes or "")
            )
            stderr = (
                stderr_bytes.decode("utf-8", errors="replace")
                if isinstance(stderr_bytes, bytes)
                else str(stderr_bytes or "")
            )

            # ---- 7. 超时则抛出异常 ----
            if is_timeout:
                timeout_msg = (
                    f"Command '{shell_cmd}' timed out after "
                    f"{effective_timeout:.0f}s and was killed."
                )
                if stderr:
                    timeout_msg += f"\nStderr:\n{stderr}"
                raise SandboxTimeoutError(
                    timeout_msg,
                    timeout_seconds=effective_timeout,
                    details={
                        "command": shell_cmd,
                        "sandbox_id": sandbox_id,
                        "stdout": stdout,
                    },
                )

            # ---- 8. 非零退出码则抛出异常 ----
            if exit_code != 0:
                raise SandboxExecutionError(
                    f"Command '{shell_cmd}' exited with code {exit_code}.",
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    details={
                        "command": shell_cmd,
                        "sandbox_id": sandbox_id,
                    },
                )

            # ---- 9. 正常返回 ----
            return SandboxResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                is_timeout=False,
            )

        except SandboxError:
            # 自定义异常直接向上传播
            raise
        except DockerException as exc:
            raise SandboxError(
                f"Docker operation failed: {exc}",
                details={"sandbox_id": sandbox_id, "command": shell_cmd},
            ) from exc
        except OSError as exc:
            raise SandboxError(
                f"Filesystem operation failed: {exc}",
                details={"sandbox_id": sandbox_id},
            ) from exc

        finally:
            # ---- 10. 资源清理（保证一定执行） ----
            # 销毁容器
            if container is not None:
                try:
                    await asyncio.to_thread(container.remove, force=True)
                except Exception:
                    pass

            # 删除临时目录副本，防止磁盘空间泄漏
            if sandbox_dir is not None and sandbox_dir.exists():
                try:
                    await asyncio.to_thread(shutil.rmtree, str(sandbox_dir))
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

async def run_sandbox(
    command: str | list[str],
    source_dir: Path,
    timeout: Optional[float] = None,
) -> SandboxResult:
    """快捷执行沙箱命令（异步版）。

    Args:
        command: 要执行的命令。
        source_dir: 要挂载到 /app 的宿主机目录（原始目录不会被修改）。
        timeout: 超时时间（秒），默认使用 Sandbox.EXEC_TIMEOUT。

    Returns:
        SandboxResult 对象。

    Raises:
        SandboxExecutionError: 命令执行失败。
        SandboxTimeoutError: 执行超时。
    """
    sandbox = Sandbox()
    return await sandbox.execute(command, source_dir, timeout=timeout)


def run_sandbox_sync(
    command: str | list[str],
    source_dir: Path,
    timeout: Optional[float] = None,
) -> SandboxResult:
    """快捷执行沙箱命令（同步版，供 LangChain @tool 等同步上下文使用）。

    自动检测当前线程是否有运行中的事件循环：
    - 有运行中的循环 → 在新线程中创建独立事件循环执行
    - 无运行中的循环 → 直接创建事件循环执行

    Args:
        command: 要执行的命令。
        source_dir: 要挂载到 /app 的宿主机目录（原始目录不会被修改）。
        timeout: 超时时间（秒），默认使用 Sandbox.EXEC_TIMEOUT。

    Returns:
        SandboxResult 对象。

    Raises:
        SandboxExecutionError: 命令执行失败。
        SandboxTimeoutError: 执行超时。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 当前线程没有运行中的事件循环 → 直接创建新的执行
        return asyncio.run(run_sandbox(command, source_dir, timeout))

    # 当前线程有运行中的事件循环 → 在新线程中执行，避免冲突
    result_container: list[SandboxResult] = []
    error_container: list[Exception] = []

    def _run_in_thread() -> None:
        try:
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            result_container.append(
                new_loop.run_until_complete(
                    run_sandbox(command, source_dir, timeout)
                )
            )
        except Exception as exc:
            error_container.append(exc)
        finally:
            new_loop.close()

    thread = threading.Thread(target=_run_in_thread, daemon=True)
    thread.start()
    thread.join()

    if error_container:
        raise error_container[0]
    return result_container[0]

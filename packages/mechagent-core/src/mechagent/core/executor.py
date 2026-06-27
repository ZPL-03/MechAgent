"""作业执行器抽象接口。

定义提交、轮询、获取结果与取消作业的统一契约，支持本地、远程工作站、HPC（如 Slurm）
和容器等执行后端。执行后端通过工厂注册名、构造函数和配置接入，与求解器、网格器保持
一致的注册/工厂/配置模式。内置同步本地命令执行器 ``LocalCommandExecutor``。
"""

from __future__ import annotations

import math
import os
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mechagent.core.exceptions import ExecutorError


class JobStatus(str, Enum):
    """作业状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})


class ExecutorConfig(BaseModel):
    """作业执行器运行配置。

    Args:
        work_dir: 默认作业工作目录。
        default_timeout: 默认作业超时，单位为 s。
        poll_interval: 默认轮询间隔，单位为 s。

    Returns:
        ExecutorConfig: 经过校验的执行器配置。

    Raises:
        pydantic.ValidationError: 当字段不满足类型或范围约束时抛出。

    Example:
        >>> ExecutorConfig(work_dir="mechagent_output", default_timeout=600)
        ExecutorConfig(...)
    """

    model_config = ConfigDict(extra="forbid")

    work_dir: Path = Field(default=Path("mechagent_output"))
    default_timeout: int = Field(default=3600, ge=1)
    poll_interval: float = Field(default=0.5, gt=0)

    @field_validator("poll_interval")
    @classmethod
    def _poll_interval_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "executor.poll_interval 必须是有限数值。"
            raise ValueError(msg)
        return value


class JobSpec(BaseModel):
    """作业规格。

    Args:
        command: 可执行命令及参数列表，第一个元素为可执行文件。
        work_dir: 作业工作目录；为空时使用执行器默认目录。
        env: 追加的环境变量。
        timeout: 作业超时，单位为 s；为空时使用执行器默认超时。
        labels: 作业标签，用于检索与审计。

    Returns:
        JobSpec: 经过校验的作业规格。

    Raises:
        pydantic.ValidationError: 当字段不满足 schema 时抛出。

    Example:
        >>> JobSpec(command=["ccx", "model"])
        JobSpec(...)
    """

    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(min_length=1)
    work_dir: Optional[Path] = None
    env: dict[str, str] = Field(default_factory=dict)
    timeout: Optional[int] = Field(default=None, ge=1)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("command")
    @classmethod
    def _command_entries_must_be_non_empty(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            msg = "job.command 不能包含空白片段。"
            raise ValueError(msg)
        return value


class JobResult(BaseModel):
    """作业执行结果。

    Args:
        job_id: 作业标识。
        status: 作业终态。
        return_code: 进程返回码。
        wall_time: 实际耗时，单位为 s。
        output_files: 产物文件路径列表。
        stdout: 标准输出文本。
        stderr: 标准错误文本。
        metadata: 附加诊断信息。
        error_message: 失败诊断信息。

    Returns:
        JobResult: 统一作业结果对象。

    Raises:
        pydantic.ValidationError: 当结果字段不满足 schema 时抛出。

    Example:
        >>> JobResult(job_id="abc", status=JobStatus.SUCCEEDED, return_code=0, wall_time=0.1)
        JobResult(...)
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus
    return_code: Optional[int] = None
    wall_time: float = Field(ge=0)
    output_files: list[Path] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None

    @field_validator("wall_time")
    @classmethod
    def _wall_time_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "job.wall_time 必须是有限数值。"
            raise ValueError(msg)
        return value


class AbstractJobExecutor(ABC):
    """所有作业执行器适配器必须实现的抽象基类。

    ``run()`` 是固定模板方法，按提交、轮询至终态、获取结果执行；子类只实现提交、状态查询、
    结果获取和取消。本地执行器同步执行，远程/HPC/容器执行器异步提交并轮询。

    Args:
        config: 执行器配置。

    Returns:
        AbstractJobExecutor: 具体执行器实例。

    Raises:
        TypeError: 当子类定义与模板方法冲突的 run 时抛出。

    Example:
        >>> executor = LocalCommandExecutor(ExecutorConfig())
        >>> executor.run(JobSpec(command=["python", "-c", "print(1)"])).status
        <JobStatus.SUCCEEDED: 'succeeded'>
    """

    config: ExecutorConfig

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "run" in cls.__dict__:
            msg = "AbstractJobExecutor.run() 是固定模板方法，子类只实现提交、状态、结果和取消。"
            raise TypeError(msg)

    def __init__(self, config: ExecutorConfig) -> None:
        self.config = config
        self.config.work_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def submit(self, spec: JobSpec) -> str:
        """提交作业。

        Args:
            spec: 作业规格。

        Returns:
            str: 作业标识。

        Raises:
            ExecutorError: 当作业无法提交时抛出。
        """

    @abstractmethod
    def status(self, job_id: str) -> JobStatus:
        """查询作业状态。

        Args:
            job_id: 作业标识。

        Returns:
            JobStatus: 当前作业状态。

        Raises:
            ExecutorError: 当作业标识未知时抛出。
        """

    @abstractmethod
    def result(self, job_id: str) -> JobResult:
        """获取作业结果。

        Args:
            job_id: 作业标识。

        Returns:
            JobResult: 作业结果。

        Raises:
            ExecutorError: 当作业标识未知或尚未结束时抛出。
        """

    @abstractmethod
    def cancel(self, job_id: str) -> None:
        """取消作业。

        Args:
            job_id: 作业标识。

        Returns:
            无。

        Raises:
            ExecutorError: 当作业标识未知时抛出。
        """

    def run(self, spec: JobSpec, *, poll_interval: Optional[float] = None) -> JobResult:
        """按固定模板提交并等待作业结束。

        Args:
            spec: 作业规格。
            poll_interval: 轮询间隔，单位为 s；为空时使用执行器配置。

        Returns:
            JobResult: 作业终态结果。

        Raises:
            ExecutorError: 当提交、状态查询或结果获取失败时抛出。

        Example:
            >>> executor.run(JobSpec(command=["python", "-c", "print(1)"]))
            JobResult(status=<JobStatus.SUCCEEDED: 'succeeded'>, ...)
        """

        interval = poll_interval if poll_interval is not None else self.config.poll_interval
        timeout = spec.timeout if spec.timeout is not None else self.config.default_timeout
        start = time.perf_counter()
        job_id = self.submit(spec)
        while self.status(job_id) not in TERMINAL_JOB_STATUSES:
            if time.perf_counter() - start > timeout:
                self.cancel(job_id)
                break
            time.sleep(interval)
        return self.result(job_id)


class LocalCommandExecutor(AbstractJobExecutor):
    """同步本地命令执行器。

    在本机以子进程方式执行命令，提交即同步完成并保存终态结果。作为执行器抽象的参考实现
    与默认后端，远程工作站、HPC 和容器执行器以同一契约扩展。

    Args:
        config: 执行器配置。

    Returns:
        LocalCommandExecutor: 本地命令执行器实例。

    Raises:
        OSError: 当工作目录无法创建时抛出。

    Example:
        >>> LocalCommandExecutor(ExecutorConfig()).run(JobSpec(command=["python", "-c", "pass"]))
        JobResult(...)
    """

    def __init__(self, config: ExecutorConfig) -> None:
        super().__init__(config)
        self._jobs: dict[str, JobResult] = {}

    def submit(self, spec: JobSpec) -> str:
        job_id = uuid.uuid4().hex[:12]
        work_dir = spec.work_dir if spec.work_dir is not None else self.config.work_dir
        work_dir.mkdir(parents=True, exist_ok=True)
        timeout = spec.timeout if spec.timeout is not None else self.config.default_timeout
        env = {**os.environ, **spec.env} if spec.env else None
        start = time.perf_counter()
        try:
            completed = subprocess.run(  # noqa: S603 - 命令来自结构化作业规格，非 shell 调用
                spec.command,
                cwd=work_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._jobs[job_id] = JobResult(
                job_id=job_id,
                status=JobStatus.FAILED,
                wall_time=time.perf_counter() - start,
                error_message=f"作业超过 {timeout}s 超时。",
            )
            return job_id
        except OSError as exc:
            self._jobs[job_id] = JobResult(
                job_id=job_id,
                status=JobStatus.FAILED,
                wall_time=time.perf_counter() - start,
                error_message=str(exc),
            )
            return job_id
        status = JobStatus.SUCCEEDED if completed.returncode == 0 else JobStatus.FAILED
        self._jobs[job_id] = JobResult(
            job_id=job_id,
            status=status,
            return_code=completed.returncode,
            wall_time=time.perf_counter() - start,
            stdout=completed.stdout,
            stderr=completed.stderr,
            error_message=None if status is JobStatus.SUCCEEDED else "命令返回非零退出码。",
        )
        return job_id

    def status(self, job_id: str) -> JobStatus:
        return self._lookup(job_id).status

    def result(self, job_id: str) -> JobResult:
        return self._lookup(job_id)

    def cancel(self, job_id: str) -> None:
        record = self._lookup(job_id)
        if record.status not in TERMINAL_JOB_STATUSES:
            self._jobs[job_id] = record.model_copy(update={"status": JobStatus.CANCELLED})

    def _lookup(self, job_id: str) -> JobResult:
        record = self._jobs.get(job_id)
        if record is None:
            msg = f"未知作业: {job_id}"
            raise ExecutorError(msg)
        return record

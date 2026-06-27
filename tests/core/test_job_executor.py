"""作业执行器抽象接口与注册工厂测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pytest
from pydantic import ValidationError

from mechagent.core import (
    AbstractJobExecutor,
    ExecutorConfig,
    ExecutorError,
    JobResult,
    JobSpec,
    JobStatus,
    LocalCommandExecutor,
    create_executor,
    register_executor,
    registered_executors,
    unregister_executor,
)


def test_local_executor_runs_command(tmp_path: Path) -> None:
    executor = LocalCommandExecutor(ExecutorConfig(work_dir=tmp_path))
    result = executor.run(JobSpec(command=[sys.executable, "-c", "print('hello')"]))
    assert result.status is JobStatus.SUCCEEDED
    assert result.return_code == 0
    assert "hello" in result.stdout
    assert result.wall_time >= 0


def test_local_executor_reports_failure(tmp_path: Path) -> None:
    executor = LocalCommandExecutor(ExecutorConfig(work_dir=tmp_path))
    result = executor.run(JobSpec(command=[sys.executable, "-c", "import sys; sys.exit(3)"]))
    assert result.status is JobStatus.FAILED
    assert result.return_code == 3
    assert result.error_message is not None


def test_local_executor_unknown_job_raises(tmp_path: Path) -> None:
    executor = LocalCommandExecutor(ExecutorConfig(work_dir=tmp_path))
    with pytest.raises(ExecutorError):
        executor.result("missing")
    with pytest.raises(ExecutorError):
        executor.cancel("missing")


def test_default_executor_registered(tmp_path: Path) -> None:
    assert "local" in registered_executors()
    executor = create_executor("local", ExecutorConfig(work_dir=tmp_path))
    assert isinstance(executor, LocalCommandExecutor)


def test_unknown_executor_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_executor("missing-executor", ExecutorConfig(work_dir=tmp_path))


def test_executor_registry_roundtrip() -> None:
    register_executor("stub-executor", LocalCommandExecutor)
    try:
        assert "stub-executor" in registered_executors()
    finally:
        unregister_executor("stub-executor")
    assert "stub-executor" not in registered_executors()


def test_run_is_a_fixed_template() -> None:
    with pytest.raises(TypeError):

        class _Bad(AbstractJobExecutor):
            def submit(self, spec: JobSpec) -> str:
                _ = spec
                return "job"

            def status(self, job_id: str) -> JobStatus:
                _ = job_id
                return JobStatus.SUCCEEDED

            def result(self, job_id: str) -> JobResult:
                return JobResult(job_id=job_id, status=JobStatus.SUCCEEDED, wall_time=0.0)

            def cancel(self, job_id: str) -> None:
                _ = job_id
                return None

            def run(  # 覆盖模板方法 -> TypeError
                self, spec: JobSpec, *, poll_interval: Optional[float] = None
            ) -> JobResult:
                _ = (spec, poll_interval)
                raise NotImplementedError


def test_job_spec_rejects_empty_command() -> None:
    with pytest.raises(ValidationError):
        JobSpec(command=[])
    with pytest.raises(ValidationError):
        JobSpec(command=["   "])


def test_job_result_rejects_non_finite_wall_time() -> None:
    with pytest.raises(ValidationError):
        JobResult(job_id="job", status=JobStatus.SUCCEEDED, wall_time=float("inf"))

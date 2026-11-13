"""独立执行进程。任务仅从本地数据库读取，不接受任意命令。"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from threading import Event, Thread

import psutil

from mechagent.app import MechAgent
from mechagent.evidence import atomic_json, public_value, sha256, write_manifest
from mechagent.orchestrator.progress import progress_sink
from mechagent.redaction import redact_sensitive_text
from mechagent.runtime.process import process_boundary
from mechagent.runtime.store import JobStore
from mechagent.ui.visualization import visualizations_from_summary


def _collect_process_resources() -> dict[str, float | int]:
    """采集 worker 及当前可见子进程的累计 CPU 时间和峰值常驻内存。"""

    process = psutil.Process()
    try:
        processes = [process, *process.children(recursive=True)]
    except psutil.Error:
        processes = [process]
    cpu_user = 0.0
    cpu_system = 0.0
    peak_rss = 0
    measured = False
    for candidate in processes:
        try:
            times = candidate.cpu_times()
            memory = candidate.memory_info()
        except psutil.Error:
            continue
        cpu_user += max(0.0, float(times.user))
        cpu_system += max(0.0, float(times.system))
        peak_rss = max(peak_rss, int(memory.rss))
        measured = True
    if not measured:
        return {}
    return {
        "cpu_user_seconds": cpu_user,
        "cpu_system_seconds": cpu_system,
        "peak_rss_bytes": peak_rss,
    }


def execute(store: JobStore, job_id: str, token: str) -> None:
    started = time.perf_counter()
    job = store.get(job_id)
    directory = store.directory(job_id)
    stop = Event()
    secrets: tuple[str, ...] = ()

    def heartbeat() -> None:
        try:
            while not stop.wait(1):
                store.heartbeat(job_id, token)
        except Exception:
            # 心跳无法持久化时禁止继续产生无法追踪的求解进程；Job Object 清理后代。
            os._exit(2)

    thread = Thread(target=heartbeat, name="job-heartbeat", daemon=True)
    thread.start()
    try:
        if not job["config_hash"]:
            raise ValueError("历史作业缺少配置文件哈希；请显式重新提交该作业。")
        if sha256(Path(job["config_path"])) != job["config_hash"]:
            raise ValueError("配置文件与提交时的哈希不一致；请使用当前配置显式重试。")
        agent = MechAgent.from_config(job["config_path"])
        secrets = (agent.config.llm.api_key,)
        agent.config.output.output_dir = directory / "runs"
        with progress_sink(lambda event: store.event(job_id, token, public_value(event, secrets))):
            result = agent.run(job["request"], use_llm_agents=bool(job["use_llm_agents"]))
        response = public_value(
            {
                "success": bool(result.summary.get("success", False)),
                "report": result.report,
                "summary": result.summary,
                "visualizations": [
                    item.to_dict() for item in visualizations_from_summary(result.summary)
                ],
                "metadata": {
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "manifest_path": str(result.manifest_path),
                },
            },
            secrets,
            sanitize_paths=True,
        )
        status = "succeeded" if response["success"] else "failed"
        error = None if response["success"] else "工作流未通过；请检查报告与错误摘要。"
        code = None if response["success"] else "workflow_failed"
    except Exception as exc:
        status, code = "failed", "worker_error"
        error = redact_sensitive_text(str(exc), extra_secrets=secrets)
        response = {
            "success": False,
            "error": error,
            "summary": {
                "success": False,
                "errors": [{"node": "worker", "message": error}],
                "tasks": [],
            },
            "visualizations": [],
            "metadata": {"duration_ms": int((time.perf_counter() - started) * 1000)},
        }
    try:
        response = public_value(response, secrets, sanitize_paths=True)
        atomic_json(directory / "result.json", response)
        write_manifest(directory, status=status, details={"job_id": job_id, "error_code": code})
        store.finish(
            job_id,
            token,
            status,
            error=error,
            error_code=code,
            result=response,
            resources=_collect_process_resources(),
        )
    finally:
        stop.set()
        thread.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    store = JobStore(args.database)
    with process_boundary():
        if not store.register(args.job_id, args.token, os.getpid(), psutil.Process().create_time()):
            return
        if store.get(args.job_id)["status"] == "running":
            execute(store, args.job_id, args.token)


if __name__ == "__main__":
    main()

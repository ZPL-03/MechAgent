"""编排阶段进度事件。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Callable, Literal, TypedDict

StageName = Literal[
    "planner",
    "designer",
    "mesh",
    "solver",
    "postproc",
    "analyst",
    "reporter",
]
StageStatus = Literal["running", "complete", "failed"]


class ProgressEvent(TypedDict):
    """工作流阶段事件。"""

    stage: StageName
    status: StageStatus
    message: str
    timestamp: str


ProgressSink = Callable[[ProgressEvent], None]

_PROGRESS_SINK: ContextVar[ProgressSink | None] = ContextVar(
    "mechagent_progress_sink",
    default=None,
)


@contextmanager
def progress_sink(sink: ProgressSink) -> Iterator[None]:
    """绑定当前执行上下文的进度事件接收器。"""

    token = _PROGRESS_SINK.set(sink)
    try:
        yield
    finally:
        _PROGRESS_SINK.reset(token)


def emit_progress(stage: StageName, status: StageStatus, message: str = "") -> None:
    """向当前上下文发送阶段进度事件。"""

    sink = _PROGRESS_SINK.get()
    if sink is None:
        return
    sink(
        {
            "stage": stage,
            "status": status,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    )

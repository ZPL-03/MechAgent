"""运行标识生成。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo


def new_run_id(request: str) -> str:
    """生成一次求解运行的唯一标识。

    Args:
        request: 用户自然语言请求。

    Returns:
        str: `RUN_<timestamp>_<short_hash>` 格式的运行标识。

    Raises:
        无。

    Example:
        >>> new_run_id("结构静力分析").startswith("RUN_")
        True
    """

    timestamp = datetime.now(tz=ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S_%f")
    short_hash = hashlib.sha1(request.encode("utf-8")).hexdigest()[:8]
    return f"RUN_{timestamp}_{short_hash}"

"""公开文本脱敏工具。"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable


def redact_sensitive_text(message: str, extra_secrets: Iterable[str] = ()) -> str:
    """脱敏公开错误文本和 trace 文本。"""

    redacted = message
    for secret in [*extra_secrets, os.environ.get("API_KEY", "")]:
        if len(secret) >= 4:
            redacted = redacted.replace(secret, "***")
    redacted = re.sub(r"\bsk-[A-Za-z0-9_\-]{8,}\b", "sk-***", redacted)
    redacted = re.sub(r"\btp-[A-Za-z0-9_\-]{8,}\b", "tp-***", redacted)
    redacted = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+", "Bearer ***", redacted)
    redacted = re.sub(
        r"(?i)([?&](?:api[_-]?key|token|access_token)=)[^&\s]+",
        r"\1***",
        redacted,
    )
    return redacted

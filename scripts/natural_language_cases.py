"""独立自然语言静力验证案例。"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "packages" / "mechagent-core" / "src"
APP_SRC = ROOT / "packages" / "mechagent" / "src"
for src in (str(ROOT), str(CORE_SRC), str(APP_SRC)):
    if src not in sys.path:
        sys.path.insert(0, src)

from mechagent.examples import all_examples  # noqa: E402


@dataclass(frozen=True)
class StaticLanguageCase:
    """自然语言静力案例。"""

    case_id: str
    request: str
    geometry_type: str
    load_type: str
    model_case_id: str


STATIC_LANGUAGE_CASES = tuple(
    StaticLanguageCase(
        case_id=example.case_id,
        request=example.request,
        geometry_type=example.geometry_type,
        load_type=example.load_type,
        model_case_id=example.model_case_id,
    )
    for example in all_examples(capability_id="structural_static")
)

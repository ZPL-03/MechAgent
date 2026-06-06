"""求解器模板方法测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mechagent.core.solver import AbstractSolver, SolverResult


def test_solver_subclass_cannot_override_run() -> None:
    with pytest.raises(TypeError):

        class BadSolver(AbstractSolver):
            def generate_input(self, _model_params):  # type: ignore[no-untyped-def]
                return Path("x")

            def solve(self, _input_file: Path) -> SolverResult:
                return SolverResult(success=True, wall_time=0.0)

            def extract_results(self, _result: SolverResult) -> dict[str, object]:
                return {}

            def run(self, _model_params):  # type: ignore[no-untyped-def]
                return {}

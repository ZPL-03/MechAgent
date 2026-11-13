"""求解器模板方法测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mechagent.core.solver import AbstractSolver, SolverConfig, SolverResult
from mechagent.core.validation import tc01_model_params


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


def test_solver_template_exposes_result_provenance(tmp_path: Path) -> None:
    class _Solver(AbstractSolver):
        def generate_input(self, _model_params):  # type: ignore[no-untyped-def]
            path = self.config.work_dir / "case.inp"
            path.write_text("*HEADING\n", encoding="utf-8")
            return path

        def solve(self, input_file: Path) -> SolverResult:
            output = input_file.with_suffix(".frd")
            output.write_bytes(b"result")
            return SolverResult(success=True, wall_time=0.0, output_files=[output])

        def extract_results(self, _result: SolverResult) -> dict[str, object]:
            return {}

    result = _Solver(SolverConfig(work_dir=tmp_path)).run(tc01_model_params())

    assert isinstance(result["input_sha256"], str)
    assert [item["path"] for item in result["artifacts"]] == ["case.frd", "case.inp"]

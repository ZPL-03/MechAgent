"""核心工厂测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mechagent.core import (
    create_mesher,
    create_solver,
    register_mesher,
    register_solver,
    registered_meshers,
    registered_solvers,
    unregister_mesher,
    unregister_solver,
)
from mechagent.core.mesher import AbstractMesher, MeshConfig, MeshResult
from mechagent.core.models import ModelParams
from mechagent.core.solver import AbstractSolver, SolverConfig, SolverResult


def test_create_calculix_solver() -> None:
    solver = create_solver("calculix", SolverConfig())

    assert solver.__class__.__name__ == "CalculiXAdapter"
    assert "calculix" in registered_solvers()


def test_create_solver_lookup_is_case_and_space_tolerant() -> None:
    solver = create_solver(" CALCULIX ", SolverConfig())

    assert solver.__class__.__name__ == "CalculiXAdapter"


def test_create_calculix_inp_mesher() -> None:
    mesher = create_mesher("calculix-inp", MeshConfig())

    assert mesher.__class__.__name__ == "CalculiXInpMesher"
    assert "calculix-inp" in registered_meshers()


def test_create_mesher_lookup_is_case_and_space_tolerant() -> None:
    mesher = create_mesher(" CALCULIX-INP ", MeshConfig())

    assert mesher.__class__.__name__ == "CalculiXInpMesher"


def test_unknown_solver_raises() -> None:
    with pytest.raises(ValueError):
        create_solver("unknown", SolverConfig())


def test_register_custom_solver() -> None:
    register_solver("unit-test-solver", DummySolver)
    try:
        solver = create_solver("unit-test-solver", SolverConfig())

        assert isinstance(solver, DummySolver)
    finally:
        unregister_solver("unit-test-solver")

    with pytest.raises(ValueError, match="未知求解器"):
        create_solver("unit-test-solver", SolverConfig())


def test_register_custom_mesher() -> None:
    register_mesher("unit-test-mesher", DummyMesher)
    try:
        mesher = create_mesher("unit-test-mesher", MeshConfig())

        assert isinstance(mesher, DummyMesher)
    finally:
        unregister_mesher("unit-test-mesher")

    with pytest.raises(ValueError, match="未知网格器"):
        create_mesher("unit-test-mesher", MeshConfig())


def test_duplicate_registration_requires_replace_flag() -> None:
    with pytest.raises(ValueError, match="求解器已注册"):
        register_solver("calculix", DummySolver)


def test_registration_rejects_names_with_outer_whitespace() -> None:
    with pytest.raises(ValueError, match="注册名称不能包含首尾空白"):
        register_solver(" unit-test-solver ", DummySolver)
    with pytest.raises(ValueError, match="注册名称不能包含首尾空白"):
        register_mesher(" unit-test-mesher ", DummyMesher)


class DummySolver(AbstractSolver):
    def generate_input(self, _model_params: ModelParams) -> Path:
        return self.config.work_dir / "dummy.inp"

    def solve(self, _input_file: Path) -> SolverResult:
        return SolverResult(success=True, wall_time=0.0)

    def extract_results(self, _result: SolverResult) -> dict[str, object]:
        return {"success": True}


class DummyMesher(AbstractMesher):
    def generate(self, _model_params: ModelParams) -> MeshResult:
        return MeshResult(success=True)

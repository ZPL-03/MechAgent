"""CAD 内核抽象接口与注册工厂测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mechagent.core import (
    AbstractCADKernel,
    CADConfig,
    CADError,
    CADGeometrySummary,
    create_cad_kernel,
    register_cad_kernel,
    registered_cad_kernels,
    unregister_cad_kernel,
)


def _summary() -> CADGeometrySummary:
    return CADGeometrySummary(
        source_format="step",
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=(100.0, 20.0, 20.0),
        volume=40000.0,
        surface_area=9600.0,
        solid_count=1,
        face_count=6,
        edge_count=12,
    )


class _StubKernel(AbstractCADKernel):
    def load(self, source: Path) -> Any:
        return {"source": source}

    def repair(self, shape: Any) -> Any:
        return shape

    def summarize(self, shape: Any) -> CADGeometrySummary:
        _ = shape
        return _summary()


class _FailingKernel(AbstractCADKernel):
    def load(self, source: Path) -> Any:
        _ = source
        msg = "不支持的格式"
        raise CADError(msg)

    def repair(self, shape: Any) -> Any:
        return shape

    def summarize(self, shape: Any) -> CADGeometrySummary:
        _ = shape
        return _summary()


def test_import_model_returns_success(tmp_path: Path) -> None:
    kernel = _StubKernel(CADConfig(work_dir=tmp_path))
    result = kernel.import_model(tmp_path / "bracket.step")
    assert result.success is True
    assert result.summary is not None
    assert result.summary.solid_count == 1
    assert result.wall_time >= 0


def test_import_model_captures_failure(tmp_path: Path) -> None:
    kernel = _FailingKernel(CADConfig(work_dir=tmp_path))
    result = kernel.import_model(tmp_path / "bad.xyz")
    assert result.success is False
    assert result.summary is None
    assert result.error_message == "不支持的格式"


def test_import_model_is_a_fixed_template() -> None:
    with pytest.raises(TypeError):

        class _Bad(AbstractCADKernel):
            def load(self, source: Path) -> Any:
                return source

            def repair(self, shape: Any) -> Any:
                return shape

            def summarize(self, shape: Any) -> CADGeometrySummary:
                _ = shape
                return _summary()

            def import_model(self, source: Path) -> Any:  # 覆盖模板方法 -> TypeError
                _ = source
                raise NotImplementedError


def test_cad_kernel_registry_roundtrip(tmp_path: Path) -> None:
    register_cad_kernel("stub-cad", _StubKernel)
    try:
        assert "stub-cad" in registered_cad_kernels()
        kernel = create_cad_kernel("stub-cad", CADConfig(work_dir=tmp_path))
        assert isinstance(kernel, _StubKernel)
    finally:
        unregister_cad_kernel("stub-cad")
    assert "stub-cad" not in registered_cad_kernels()


def test_unknown_cad_kernel_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_cad_kernel("missing-cad", CADConfig(work_dir=tmp_path))


def test_summary_rejects_non_finite_measures() -> None:
    with pytest.raises(ValidationError):
        CADGeometrySummary(
            source_format="step",
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(1.0, 1.0, 1.0),
            volume=float("inf"),
            surface_area=6.0,
            solid_count=1,
            face_count=6,
            edge_count=12,
        )

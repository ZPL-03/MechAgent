"""工程规则检查测试。"""

from __future__ import annotations

import pytest

from mechagent.core.models import (
    ElementType,
    GeometrySpec,
    GeometryType,
    LoadSpec,
    LoadType,
    MeshSpec,
)
from mechagent.core.rules import (
    check_parameter_ranges,
    check_static_execution_contract,
    ensure_parameter_ranges,
    ensure_static_execution_contract,
)
from mechagent.core.validation import tc01_model_params, tc02_model_params, tc03_model_params


def test_parameter_ranges_accept_valid_benchmark_model() -> None:
    assert check_parameter_ranges(tc01_model_params()) == []


def test_parameter_ranges_accept_valid_solid_model() -> None:
    assert check_parameter_ranges(tc03_model_params()) == []


def test_parameter_ranges_use_meshed_span_for_reduced_dimension_models() -> None:
    beam_base = tc01_model_params()
    slender_beam = beam_base.model_copy(
        update={
            "geometry": GeometrySpec(
                type=GeometryType.BEAM,
                dimensions={"length": 1000.0, "width": 2.0, "height": 4.0},
            )
        }
    )
    plate_base = tc02_model_params()
    thin_plate = plate_base.model_copy(
        update={
            "geometry": GeometrySpec(
                type=GeometryType.PLATE,
                dimensions={"length": 300.0, "width": 200.0, "thickness": 1.0},
            )
        }
    )

    assert check_parameter_ranges(slender_beam) == []
    assert check_parameter_ranges(thin_plate) == []


def test_parameter_ranges_reject_solid_seed_larger_than_smallest_dimension() -> None:
    base = tc03_model_params()
    params = base.model_copy(
        update={"mesh": MeshSpec(element_type=ElementType.C3D8R, seed_size=25)}
    )

    violations = check_parameter_ranges(params)

    assert violations[0].field == "mesh.seed_size"
    assert "代表长度" in violations[0].message


def test_parameter_ranges_reject_too_small_beam_length() -> None:
    params = tc01_model_params().model_copy(
        update={
            "geometry": GeometrySpec(
                type=GeometryType.BEAM,
                dimensions={"length": 1.0, "width": 20.0, "height": 40.0},
            )
        }
    )

    violations = check_parameter_ranges(params)

    assert violations[0].field == "geometry.dimensions.length"


def test_ensure_parameter_ranges_raises_readable_error() -> None:
    params = tc01_model_params().model_copy(
        update={
            "geometry": GeometrySpec(
                type=GeometryType.BEAM,
                dimensions={"length": 1.0, "width": 20.0, "height": 40.0},
            )
        }
    )

    with pytest.raises(ValueError, match="仿真参数超出工程规则范围"):
        ensure_parameter_ranges(params)


def test_static_execution_contract_accepts_verified_static_models() -> None:
    assert check_static_execution_contract(tc01_model_params()) == []
    assert check_static_execution_contract(tc02_model_params()) == []
    assert check_static_execution_contract(tc03_model_params()) == []


def test_static_execution_contract_rejects_beam_with_plate_element() -> None:
    base = tc01_model_params()
    params = base.model_copy(
        update={"mesh": MeshSpec(element_type=ElementType.S4, seed_size=base.mesh.seed_size)}
    )
    missing_dimensions = base.model_copy(
        update={
            "geometry": GeometrySpec(
                type=GeometryType.BEAM,
                dimensions={"length": 1000.0},
            )
        }
    )

    violations = check_static_execution_contract(params)
    missing_violations = check_static_execution_contract(missing_dimensions)

    assert violations[0].field == "mesh.element_type"
    assert "B31" in violations[0].message
    assert [item.field for item in missing_violations[:2]] == [
        "geometry.dimensions.width",
        "geometry.dimensions.height",
    ]
    assert "几何尺寸字段" in missing_violations[0].message


def test_static_execution_contract_rejects_oblique_beam_and_plate_loads() -> None:
    beam_base = tc01_model_params()
    beam_params = beam_base.model_copy(
        update={
            "loads": [
                LoadSpec(
                    type=LoadType.FORCE,
                    magnitude=1000.0,
                    region="tip",
                    direction=(0.0, -1.0, 0.05),
                )
            ]
        }
    )
    base = tc02_model_params()
    params = base.model_copy(
        update={
            "loads": [
                LoadSpec(
                    type=LoadType.PRESSURE,
                    magnitude=0.01,
                    region="top_surface",
                    direction=(0.0, -0.05, -1.0),
                )
            ]
        }
    )

    beam_violations = check_static_execution_contract(beam_params)
    violations = check_static_execution_contract(params)

    assert beam_violations[0].field == "loads.direction"
    assert "纯全局 Y 向横向载荷" in beam_violations[0].message
    assert violations[0].field == "loads.direction"
    assert "纯全局 Z 向面载荷" in violations[0].message


def test_static_execution_contract_rejects_oblique_solid_axial_load() -> None:
    base = tc03_model_params()
    params = base.model_copy(
        update={
            "loads": [
                LoadSpec(
                    type=LoadType.FORCE,
                    magnitude=1000.0,
                    region="end_face",
                    direction=(1.0, 0.05, 0.0),
                )
            ]
        }
    )

    violations = check_static_execution_contract(params)

    assert violations[0].field == "loads.direction"
    assert "纯全局 X 向端面轴向载荷" in violations[0].message


def test_ensure_static_execution_contract_raises_readable_error() -> None:
    base = tc01_model_params()
    params = base.model_copy(
        update={"mesh": MeshSpec(element_type=ElementType.S4, seed_size=base.mesh.seed_size)}
    )

    with pytest.raises(ValueError, match="仿真参数不满足结构静力执行契约"):
        ensure_static_execution_contract(params)

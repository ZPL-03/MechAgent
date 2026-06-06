"""结构静力自然语言解析测试。"""

from __future__ import annotations

import pytest
from scripts.natural_language_cases import STATIC_LANGUAGE_CASES, StaticLanguageCase

from mechagent.orchestrator.static_parser import (
    detect_static_missing_fields,
    looks_like_static_request,
    parse_static_model_params,
    split_static_simulation_requests,
)


@pytest.mark.parametrize(
    "case", STATIC_LANGUAGE_CASES, ids=[case.case_id for case in STATIC_LANGUAGE_CASES]
)
def test_static_language_cases_parse_to_model_params(case: StaticLanguageCase) -> None:
    params = parse_static_model_params(case.request)

    assert params.geometry.type.value == case.geometry_type
    assert params.loads[0].type.value == case.load_type
    assert params.case_id == case.model_case_id
    assert params.load_case
    assert params.analysis.type.value == "static"
    assert params.mesh.seed_size > 0.0


def test_parser_auto_selects_mesh_seed_size_for_beam() -> None:
    params = parse_static_model_params(STATIC_LANGUAGE_CASES[1].request)

    assert params.geometry.dimensions["length"] == 1000.0
    assert params.geometry.dimensions["width"] == 20.0
    assert params.geometry.dimensions["height"] == 40.0
    assert params.loads[0].magnitude == 1.0
    assert params.mesh.seed_size == 10.0


def test_parser_accepts_spaced_metric_beam_section_and_force() -> None:
    params = parse_static_model_params(
        "一根钢制悬臂梁，长度 2 m，截面 100 mm x 200 mm，左端固支，"
        "右端向下集中力 10 kN，做线弹性静力分析并输出最大挠度报告。"
    )

    assert params.geometry.dimensions == {"length": 2000.0, "width": 100.0, "height": 200.0}
    assert params.loads[0].type.value == "force"
    assert params.loads[0].magnitude == 10000.0
    assert params.loads[0].direction == (0.0, -1.0, 0.0)
    assert params.case_id == "STATIC-BEAM"


def test_parser_accepts_unicode_multiplication_section_and_uppercase_line_load() -> None:
    params = parse_static_model_params(
        "钢制悬臂梁，长度1m，截面20mm×40mm，左端固定，向下2KN/m均布线载荷静力分析"
    )

    assert params.geometry.dimensions == {"length": 1000.0, "width": 20.0, "height": 40.0}
    assert params.loads[0].type.value == "line_load"
    assert params.loads[0].magnitude == 2.0
    assert params.loads[0].direction == (0.0, -1.0, 0.0)


def test_parser_accepts_leading_compact_dimensions_with_unicode_multiplication() -> None:
    plate = parse_static_model_params(
        "300mm×200mm×5mm 的矩形板，材料铝，四边简支，承受10KPA均布压力静力分析"
    )
    solid = parse_static_model_params(
        "200mm×20mm×20mm长方体实体，材料钢，左端固定，右端沿正x方向承受4000N轴向拉伸静力分析"
    )

    assert plate.geometry.dimensions == {"length": 300.0, "width": 200.0, "thickness": 5.0}
    assert plate.loads[0].magnitude == 0.01
    assert solid.geometry.dimensions == {"length": 200.0, "width": 20.0, "height": 20.0}
    assert solid.loads[0].magnitude == 4000.0


def test_parser_rejects_unsplit_compound_geometry_request() -> None:
    request = "请分析一个梁板组合结构的静力响应，材料钢，长度1000mm，载荷1000N。"

    assert looks_like_static_request(request)
    assert split_static_simulation_requests(request) == (request,)
    assert detect_static_missing_fields(request) == ["单一几何类型"]
    with pytest.raises(ValueError, match="多个几何类型.*板.*梁"):
        parse_static_model_params(request)


def test_parser_auto_selects_mesh_seed_size_for_plate() -> None:
    params = parse_static_model_params(STATIC_LANGUAGE_CASES[4].request)

    assert params.geometry.dimensions["length"] == 300.0
    assert params.geometry.dimensions["width"] == 200.0
    assert params.geometry.dimensions["thickness"] == 5.0
    assert params.loads[0].magnitude == 0.01
    assert params.mesh.seed_size == 5.0


def test_parser_auto_selects_mesh_seed_size_for_solid() -> None:
    params = parse_static_model_params(STATIC_LANGUAGE_CASES[7].request)

    assert params.geometry.dimensions["length"] == 200.0
    assert params.geometry.dimensions["width"] == 20.0
    assert params.geometry.dimensions["height"] == 20.0
    assert params.loads[0].magnitude == 10.0
    assert params.mesh.seed_size == 10.0


def test_static_request_detection_is_geometry_agnostic() -> None:
    assert looks_like_static_request(STATIC_LANGUAGE_CASES[0].request)
    assert looks_like_static_request(STATIC_LANGUAGE_CASES[3].request)


def test_static_target_request_reports_missing_inputs() -> None:
    request = "梁长1000mm、截面20mmx40mm、材料钢的梁，输出最大挠度报告"

    assert looks_like_static_request(request)
    with pytest.raises(ValueError, match="固支边界.*载荷"):
        parse_static_model_params(request)
    assert detect_static_missing_fields(request) == ["固支边界", "载荷"]


def test_missing_geometry_material_and_section_are_reported() -> None:
    with pytest.raises(ValueError, match="梁长.*矩形截面尺寸.*材料"):
        parse_static_model_params("求解一个悬臂梁一端固支，一端垂直受压50KN/m的受力情况")


def test_beam_load_direction_is_required() -> None:
    request = "梁长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部1000N静力分析"

    with pytest.raises(ValueError, match="载荷方向"):
        parse_static_model_params(request)
    assert detect_static_missing_fields(request) == ["载荷方向"]


def test_solid_axial_load_direction_is_required() -> None:
    request = "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端端面承受10MPa静力分析"

    with pytest.raises(ValueError, match="端面载荷方向"):
        parse_static_model_params(request)
    assert detect_static_missing_fields(request) == ["端面载荷方向"]


def test_unsupported_compound_material_is_not_matched_as_builtin_steel() -> None:
    request = "梁长1000mm、截面20mmx40mm、材料钢筋混凝土的悬臂梁，一端固支，端部向下1000N静力分析"

    with pytest.raises(ValueError, match="材料"):
        parse_static_model_params(request)
    assert detect_static_missing_fields(request) == ["材料"]


def test_static_missing_field_detection_does_not_require_model_build() -> None:
    missing = detect_static_missing_fields("求解一个悬臂梁一端固支，一端垂直受压50KN/m的受力情况")

    assert missing == ["梁长", "矩形截面尺寸", "材料", "载荷方向"]


def test_parser_does_not_read_plate_suffix_as_elastic_modulus() -> None:
    request = (
        "plate 300mm x 200mm x 5mm, simply supported, "
        "uniform pressure 0.01MPa, nu=0.3 static analysis"
    )

    with pytest.raises(ValueError, match="材料"):
        parse_static_model_params(request)


def test_parser_does_not_read_elastic_modulus_as_plate_pressure() -> None:
    params = parse_static_model_params(
        "矩形板长300mm、宽200mm、厚5mm，E=70000MPa，nu=0.3，四边简支，承受0.01MPa均布压力"
    )

    assert params.material.E == 70000.0
    assert params.loads[0].magnitude == 0.01


def test_parser_reports_missing_pressure_when_only_elastic_modulus_has_mpa() -> None:
    with pytest.raises(ValueError, match="面载荷"):
        parse_static_model_params(
            "矩形板长300mm、宽200mm、厚5mm，E=70000MPa，nu=0.3，四边简支，进行静力分析"
        )


def test_parser_accepts_unicode_squared_pressure_unit() -> None:
    params = parse_static_model_params(
        "矩形板300mmx200mmx5mm，材料钢，四边简支，承受0.01N/mm²均布压力静力分析"
    )

    assert params.loads[0].magnitude == 0.01


def test_parser_accepts_engineering_pressure_number_and_area_units() -> None:
    decimal_pressure = parse_static_model_params(
        "矩形板300mmx200mmx5mm，材料钢，四边简支，承受.01MPa均布压力静力分析"
    )
    metric_pressure = parse_static_model_params(
        "矩形板300mmx200mmx5mm，材料钢，四边简支，承受2kN/m²均布压力静力分析"
    )
    pascal_pressure = parse_static_model_params(
        "矩形板300mmx200mmx5mm，材料钢，四边简支，承受1000N/m^2均布压力静力分析"
    )

    assert decimal_pressure.loads[0].magnitude == 0.01
    assert metric_pressure.loads[0].magnitude == 0.002
    assert pascal_pressure.loads[0].magnitude == 0.001


def test_parser_accepts_unicode_squared_elastic_modulus_unit() -> None:
    params = parse_static_model_params(
        "梁长600mm、截面25mmx30mm、弹性模量210000N/mm²、泊松比0.3的梁，一端固支，端部向下750N静力分析"
    )

    assert params.material.E == 210000.0
    assert params.loads[0].type.value == "force"
    assert params.loads[0].magnitude == 750.0


def test_parser_prefers_explicit_material_properties_over_catalog_alias() -> None:
    params = parse_static_model_params(
        "材料钢的梁，梁长1000mm、截面20mmx40mm，弹性模量70000MPa、泊松比0.33，一端固支，端部向下1000N静力分析"
    )

    assert params.material.E == 70000.0
    assert params.material.nu == 0.33
    assert params.material.rho == 7.85e-9


def test_parser_uses_catalog_material_to_fill_missing_explicit_property() -> None:
    params = parse_static_model_params(
        "材料钢的梁，梁长1000mm、截面20mmx40mm，弹性模量200000MPa，一端固支，端部向下1000N静力分析"
    )

    assert params.material.E == 200000.0
    assert params.material.nu == 0.3
    assert params.material.rho == 7.85e-9


def test_parser_normalizes_negative_force_magnitude_to_positive_value() -> None:
    params = parse_static_model_params(
        "梁长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下-1000N静力分析"
    )

    assert params.loads[0].magnitude == 1000.0
    assert params.loads[0].direction == (0.0, -1.0, 0.0)


def test_parser_normalizes_negative_pressure_magnitude_to_positive_value() -> None:
    params = parse_static_model_params(
        "矩形板长300mm、宽200mm、厚5mm，材料铝，四边简支，承受-0.01MPa均布压力静力分析"
    )

    assert params.loads[0].magnitude == 0.01
    assert params.loads[0].direction == (0.0, 0.0, -1.0)


def test_parser_accepts_upward_plate_pressure_direction() -> None:
    params = parse_static_model_params(
        "矩形板长300mm、宽200mm、厚5mm，材料铝，四边简支，承受向上0.01MPa均布压力静力分析"
    )

    assert params.loads[0].magnitude == 0.01
    assert params.loads[0].direction == (0.0, 0.0, 1.0)


def test_parser_does_not_treat_surface_position_as_upward_load_direction() -> None:
    params = parse_static_model_params(
        "梁长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，在上表面施加向下1000N端部载荷静力分析"
    )

    assert params.loads[0].direction == (0.0, -1.0, 0.0)


def test_parser_accepts_explicit_upward_beam_load_direction() -> None:
    params = parse_static_model_params(
        "梁长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向上1000N静力分析"
    )

    assert params.loads[0].direction == (0.0, 1.0, 0.0)

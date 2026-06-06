"""独立自然语言静力验证案例。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StaticLanguageCase:
    """自然语言静力案例。

    Args:
        case_id: 案例编号。
        request: 自然语言请求。
        geometry_type: 期望几何类型。
        load_type: 期望载荷类型。
        model_case_id: 期望模型能力编号。

    Returns:
        StaticLanguageCase: 案例数据对象。

    Raises:
        TypeError: 当字段类型不匹配时由 dataclass 构造阶段抛出。

    Example:
        >>> STATIC_LANGUAGE_CASES[0].case_id
        'SC-01'
    """

    case_id: str
    request: str
    geometry_type: str
    load_type: str
    model_case_id: str


STATIC_LANGUAGE_CASES = (
    StaticLanguageCase(
        case_id="SC-01",
        request="求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力的静力响应",
        geometry_type="beam",
        load_type="force",
        model_case_id="STATIC-BEAM",
    ),
    StaticLanguageCase(
        case_id="SC-02",
        request="长1m、截面2cmx4cm、材料钢的悬臂梁，一端固定，承受向下1kN/m均布线载荷，进行静力分析",
        geometry_type="beam",
        load_type="line_load",
        model_case_id="STATIC-BEAM",
    ),
    StaticLanguageCase(
        case_id="SC-03",
        request="长度800mm、宽30mm、高50mm、材料铝合金的梁，一端固支，端部向下500N，求解静力位移",
        geometry_type="beam",
        load_type="force",
        model_case_id="STATIC-BEAM",
    ),
    StaticLanguageCase(
        case_id="SC-04",
        request="梁长600mm、截面25mmx30mm、弹性模量210000MPa、泊松比0.3的梁，一端固支，端部向下750N静力分析",
        geometry_type="beam",
        load_type="force",
        model_case_id="STATIC-BEAM",
    ),
    StaticLanguageCase(
        case_id="SC-05",
        request="求解长300mm、宽200mm、厚5mm、材料铝的矩形板，四边简支，承受0.01MPa均布压力的静力响应",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
    ),
    StaticLanguageCase(
        case_id="SC-06",
        request="矩形板300mmx200mmx5mm，材料钢，四边简支，向下10kPa均布压力静力分析",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
    ),
    StaticLanguageCase(
        case_id="SC-07",
        request="矩形板0.3mx0.2mx0.005m，材料钢，四边简支，承受10000Pa均布压力，计算静力位移",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
    ),
    StaticLanguageCase(
        case_id="SC-08",
        request="长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析",
        geometry_type="solid",
        load_type="pressure",
        model_case_id="STATIC-SOLID",
    ),
    StaticLanguageCase(
        case_id="SC-09",
        request="矩形体长度200mm、宽度20mm、高度20mm、弹性模量210000MPa、泊松比0.3，左端固定，右端沿x正向4000N受拉，求解静力位移",
        geometry_type="solid",
        load_type="force",
        model_case_id="STATIC-SOLID",
    ),
    StaticLanguageCase(
        case_id="SC-10",
        request="矩形板300mmx200mmx5mm，弹性模量70000N/mm²，泊松比0.3，四边简支，承受0.01N/mm²均布压力静力分析",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
    ),
    StaticLanguageCase(
        case_id="SC-11",
        request=(
            "solve a steel beam length 1000mm, section 20mm x 40mm, "
            "cantilever fixed at one end, downward 1000N tip force static analysis"
        ),
        geometry_type="beam",
        load_type="force",
        model_case_id="STATIC-BEAM",
    ),
    StaticLanguageCase(
        case_id="SC-12",
        request=(
            "steel plate length 300mm width 200mm thickness 5mm, "
            "simply supported, uniform pressure 0.01MPa static analysis"
        ),
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
    ),
    StaticLanguageCase(
        case_id="SC-13",
        request=(
            "steel solid block length 200mm width 20mm height 20mm, "
            "fixed at left end, positive x 4000N tensile force static analysis"
        ),
        geometry_type="solid",
        load_type="force",
        model_case_id="STATIC-SOLID",
    ),
    StaticLanguageCase(
        case_id="SC-14",
        request=(
            "solve a steel beam length 1m, section 2cm x 4cm, cantilever fixed at one end, "
            "downward 1kN/m uniform line load static analysis"
        ),
        geometry_type="beam",
        load_type="line_load",
        model_case_id="STATIC-BEAM",
    ),
    StaticLanguageCase(
        case_id="SC-15",
        request=(
            "矩形板长300mm、宽200mm、厚5mm，弹性模量70GPa、泊松比0.33，"
            "四边简支，承受10kPa均布压力静力分析"
        ),
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
    ),
    StaticLanguageCase(
        case_id="SC-16",
        request=(
            "长方体实体0.2mx20mmx20mm，弹性模量210000N/mm²，泊松比0.3，"
            "左端固定，右端沿x正向4000N轴向拉伸静力分析"
        ),
        geometry_type="solid",
        load_type="force",
        model_case_id="STATIC-SOLID",
    ),
    StaticLanguageCase(
        case_id="SC-17",
        request=(
            "钢制悬臂梁，长度2m，截面100mmx200mm，左端固定，右端向下10kN集中力，输出最大挠度报告"
        ),
        geometry_type="beam",
        load_type="force",
        model_case_id="STATIC-BEAM",
    ),
    StaticLanguageCase(
        case_id="SC-18",
        request=("钢制悬臂梁，长度1m，截面20mm×40mm，左端固定，向下2KN/m均布线载荷静力分析"),
        geometry_type="beam",
        load_type="line_load",
        model_case_id="STATIC-BEAM",
    ),
    StaticLanguageCase(
        case_id="SC-19",
        request="300mm×200mm×5mm 的矩形板，材料铝，四边简支，承受10KPA均布压力静力分析",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
    ),
    StaticLanguageCase(
        case_id="SC-20",
        request=(
            "200mm×20mm×20mm长方体实体，材料钢，左端固定，右端沿正x方向承受4000N轴向拉伸静力分析"
        ),
        geometry_type="solid",
        load_type="force",
        model_case_id="STATIC-SOLID",
    ),
)

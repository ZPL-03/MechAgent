"""MechAgent 自然语言仿真示例库。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SimulationExample:
    """自然语言仿真示例。"""

    case_id: str
    title: str
    request: str
    capability_id: str
    geometry_type: str
    load_type: str
    model_case_id: str
    tags: tuple[str, ...] = ()

    @property
    def example_id(self) -> str:
        """返回公开示例编号。"""

        return self.case_id

    def to_payload(self) -> dict[str, object]:
        """返回 API 和 CLI 使用的结构化载荷。"""

        return {
            "example_id": self.example_id,
            "case_id": self.case_id,
            "title": self.title,
            "request": self.request,
            "capability_id": self.capability_id,
            "geometry_type": self.geometry_type,
            "load_type": self.load_type,
            "model_case_id": self.model_case_id,
            "tags": list(self.tags),
        }


SIMULATION_EXAMPLES: tuple[SimulationExample, ...] = (
    SimulationExample(
        case_id="SC-01",
        title="悬臂梁 · 端部集中力",
        request="求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力的静力响应",
        capability_id="structural_static",
        geometry_type="beam",
        load_type="force",
        model_case_id="STATIC-BEAM",
        tags=("梁", "集中力", "中文"),
    ),
    SimulationExample(
        case_id="SC-02",
        title="悬臂梁 · 均布线载荷",
        request="长1m、截面2cmx4cm、材料钢的悬臂梁，一端固定，承受向下1kN/m均布线载荷，进行静力分析",
        capability_id="structural_static",
        geometry_type="beam",
        load_type="line_load",
        model_case_id="STATIC-BEAM",
        tags=("梁", "线载荷", "中文"),
    ),
    SimulationExample(
        case_id="SC-03",
        title="铝合金梁 · 端部载荷",
        request="长度800mm、宽30mm、高50mm、材料铝合金的梁，一端固支，端部向下500N，求解静力位移",
        capability_id="structural_static",
        geometry_type="beam",
        load_type="force",
        model_case_id="STATIC-BEAM",
        tags=("梁", "集中力", "中文"),
    ),
    SimulationExample(
        case_id="SC-04",
        title="自定义材料梁 · 端部载荷",
        request="梁长600mm、截面25mmx30mm、弹性模量210000MPa、泊松比0.3的梁，一端固支，端部向下750N静力分析",
        capability_id="structural_static",
        geometry_type="beam",
        load_type="force",
        model_case_id="STATIC-BEAM",
        tags=("梁", "材料参数", "中文"),
    ),
    SimulationExample(
        case_id="SC-05",
        title="矩形薄板 · 均布压力",
        request="求解长300mm、宽200mm、厚5mm、材料铝的矩形板，四边简支，承受0.01MPa均布压力的静力响应",
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
        tags=("板", "压力", "中文"),
    ),
    SimulationExample(
        case_id="SC-06",
        title="钢矩形板 · kPa 压力",
        request="矩形板300mmx200mmx5mm，材料钢，四边简支，向下10kPa均布压力静力分析",
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
        tags=("板", "压力", "中文"),
    ),
    SimulationExample(
        case_id="SC-07",
        title="矩形板 · SI 单位",
        request="矩形板0.3mx0.2mx0.005m，材料钢，四边简支，承受10000Pa均布压力，计算静力位移",
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
        tags=("板", "压力", "单位换算"),
    ),
    SimulationExample(
        case_id="SC-08",
        title="长方体实体 · 端面压力",
        request="长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析",
        capability_id="structural_static",
        geometry_type="solid",
        load_type="pressure",
        model_case_id="STATIC-SOLID",
        tags=("实体", "压力", "中文"),
    ),
    SimulationExample(
        case_id="SC-09",
        title="长方体实体 · 轴向集中力",
        request="矩形体长度200mm、宽度20mm、高度20mm、弹性模量210000MPa、泊松比0.3，左端固定，右端沿x正向4000N受拉，求解静力位移",
        capability_id="structural_static",
        geometry_type="solid",
        load_type="force",
        model_case_id="STATIC-SOLID",
        tags=("实体", "集中力", "材料参数"),
    ),
    SimulationExample(
        case_id="SC-10",
        title="矩形板 · N/mm2 压力",
        request="矩形板300mmx200mmx5mm，弹性模量70000N/mm2，泊松比0.3，四边简支，承受0.01N/mm2均布压力静力分析",
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
        tags=("板", "压力", "材料参数"),
    ),
    SimulationExample(
        case_id="SC-11",
        title="Beam · Tip Force",
        request=(
            "solve a steel beam length 1000mm, section 20mm x 40mm, "
            "cantilever fixed at one end, downward 1000N tip force static analysis"
        ),
        capability_id="structural_static",
        geometry_type="beam",
        load_type="force",
        model_case_id="STATIC-BEAM",
        tags=("beam", "force", "english"),
    ),
    SimulationExample(
        case_id="SC-12",
        title="Plate · Uniform Pressure",
        request=(
            "steel plate length 300mm width 200mm thickness 5mm, "
            "simply supported, uniform pressure 0.01MPa static analysis"
        ),
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
        tags=("plate", "pressure", "english"),
    ),
    SimulationExample(
        case_id="SC-13",
        title="Solid · Tensile Force",
        request=(
            "steel solid block length 200mm width 20mm height 20mm, "
            "fixed at left end, positive x 4000N tensile force static analysis"
        ),
        capability_id="structural_static",
        geometry_type="solid",
        load_type="force",
        model_case_id="STATIC-SOLID",
        tags=("solid", "force", "english"),
    ),
    SimulationExample(
        case_id="SC-14",
        title="Beam · Uniform Line Load",
        request=(
            "solve a steel beam length 1m, section 2cm x 4cm, cantilever fixed at one end, "
            "downward 1kN/m uniform line load static analysis"
        ),
        capability_id="structural_static",
        geometry_type="beam",
        load_type="line_load",
        model_case_id="STATIC-BEAM",
        tags=("beam", "line_load", "english"),
    ),
    SimulationExample(
        case_id="SC-15",
        title="矩形板 · GPa 材料参数",
        request=(
            "矩形板长300mm、宽200mm、厚5mm，弹性模量70GPa、泊松比0.33，"
            "四边简支，承受10kPa均布压力静力分析"
        ),
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
        tags=("板", "压力", "单位换算"),
    ),
    SimulationExample(
        case_id="SC-16",
        title="长方体实体 · 混合单位",
        request=(
            "长方体实体0.2mx20mmx20mm，弹性模量210000N/mm2，泊松比0.3，"
            "左端固定，右端沿x正向4000N轴向拉伸静力分析"
        ),
        capability_id="structural_static",
        geometry_type="solid",
        load_type="force",
        model_case_id="STATIC-SOLID",
        tags=("实体", "集中力", "单位换算"),
    ),
    SimulationExample(
        case_id="SC-17",
        title="大型悬臂梁 · 10kN 载荷",
        request="钢制悬臂梁，长度2m，截面100mmx200mm，左端固定，右端向下10kN集中力，输出最大挠度报告",
        capability_id="structural_static",
        geometry_type="beam",
        load_type="force",
        model_case_id="STATIC-BEAM",
        tags=("梁", "集中力", "工程报告"),
    ),
    SimulationExample(
        case_id="SC-18",
        title="悬臂梁 · 大写单位线载荷",
        request="钢制悬臂梁，长度1m，截面20mm×40mm，左端固定，向下2KN/m均布线载荷静力分析",
        capability_id="structural_static",
        geometry_type="beam",
        load_type="line_load",
        model_case_id="STATIC-BEAM",
        tags=("梁", "线载荷", "单位换算"),
    ),
    SimulationExample(
        case_id="SC-19",
        title="矩形板 · 大写压力单位",
        request="300mm×200mm×5mm 的矩形板，材料铝，四边简支，承受10KPA均布压力静力分析",
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PLATE",
        tags=("板", "压力", "单位换算"),
    ),
    SimulationExample(
        case_id="SC-20",
        title="长方体实体 · 中文轴向拉伸",
        request="200mm×20mm×20mm长方体实体，材料钢，左端固定，右端沿正x方向承受4000N轴向拉伸静力分析",
        capability_id="structural_static",
        geometry_type="solid",
        load_type="force",
        model_case_id="STATIC-SOLID",
        tags=("实体", "集中力", "中文"),
    ),
    SimulationExample(
        case_id="SC-21",
        title="中心圆孔薄板 · 均布压力",
        request=(
            "求解长400mm、宽240mm、厚6mm、中心圆孔孔径60mm、材料钢的开孔薄板，"
            "四边简支，承受0.004MPa向下均布压力的静力响应"
        ),
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PERFORATED-PLATE",
        tags=("板", "圆孔", "压力"),
    ),
    SimulationExample(
        case_id="SC-22",
        title="Perforated Plate · Center Hole",
        request=(
            "perforated steel plate length 400mm width 240mm thickness 6mm, "
            "hole diameter 60mm, simply supported, downward uniform pressure "
            "0.004MPa static analysis"
        ),
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PERFORATED-PLATE",
        tags=("plate", "hole", "english"),
    ),
    SimulationExample(
        case_id="SC-23",
        title="偏心圆孔薄板 · 均布压力",
        request=(
            "求解长420mm、宽260mm、厚6mm、孔中心x=180mm、孔中心y=105mm、孔径50mm、"
            "材料钢的偏心圆孔薄板，四边简支，承受0.003MPa向下均布压力的静力响应"
        ),
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PERFORATED-PLATE",
        tags=("板", "偏心圆孔", "压力"),
    ),
    SimulationExample(
        case_id="SC-24",
        title="Perforated Plate · Offset Hole",
        request=(
            "perforated steel plate length 420mm width 260mm thickness 6mm, "
            "hole diameter 50mm, hole center x 180mm, hole center y 105mm, "
            "simply supported, downward uniform pressure 0.003MPa static analysis"
        ),
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PERFORATED-PLATE",
        tags=("plate", "offset_hole", "english"),
    ),
    SimulationExample(
        case_id="SC-25",
        title="多孔安装薄板 · 均布压力",
        request=(
            "求解长520mm、宽320mm、厚8mm、材料钢的多孔薄板，孔1中心x=130mm、中心y=110mm、"
            "孔径44mm，孔2中心x=260mm、中心y=210mm、孔径54mm，孔3中心x=410mm、中心y=120mm、"
            "孔径40mm，四边简支，承受0.0025MPa向下均布压力的静力响应"
        ),
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PERFORATED-PLATE",
        tags=("板", "多孔", "参数化建模", "压力"),
    ),
    SimulationExample(
        case_id="SC-26",
        title="Multi-Hole Plate · Uniform Pressure",
        request=(
            "multi-hole steel plate length 520mm width 320mm thickness 8mm, "
            "hole 1 center x 130mm center y 110mm hole diameter 44mm, "
            "hole 2 center x 260mm center y 210mm hole diameter 54mm, "
            "hole 3 center x 410mm center y 120mm hole diameter 40mm, "
            "simply supported, downward uniform pressure 0.0025MPa static analysis"
        ),
        capability_id="structural_static",
        geometry_type="plate",
        load_type="pressure",
        model_case_id="STATIC-PERFORATED-PLATE",
        tags=("plate", "multi_hole", "parametric_geometry", "pressure"),
    ),
)


def all_examples(
    *,
    capability_id: Optional[str] = None,
    model_case_id: Optional[str] = None,
    geometry_type: Optional[str] = None,
) -> tuple[SimulationExample, ...]:
    """返回按条件过滤的示例。"""

    examples = SIMULATION_EXAMPLES
    if capability_id:
        examples = tuple(item for item in examples if item.capability_id == capability_id)
    if model_case_id:
        examples = tuple(item for item in examples if item.model_case_id == model_case_id)
    if geometry_type:
        examples = tuple(item for item in examples if item.geometry_type == geometry_type)
    return examples


def example_payloads(
    *,
    capability_id: Optional[str] = None,
    model_case_id: Optional[str] = None,
    geometry_type: Optional[str] = None,
) -> list[dict[str, object]]:
    """返回示例的 JSON 载荷。"""

    return [
        item.to_payload()
        for item in all_examples(
            capability_id=capability_id,
            model_case_id=model_case_id,
            geometry_type=geometry_type,
        )
    ]

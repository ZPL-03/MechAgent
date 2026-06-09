"""SVG visualizations for MechAgent workflow summaries."""

from __future__ import annotations

import html
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_FRD_FLOAT_PATTERN = re.compile(r"[+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[Ee][+-]\d{2,3})?")


@dataclass(frozen=True)
class Visualization:
    """Single task visualization rendered as an SVG document."""

    task_id: str
    title: str
    kind: str
    svg: str
    caption: str

    def to_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "kind": self.kind,
            "svg": self.svg,
            "caption": self.caption,
        }


def visualizations_from_summary(summary: dict[str, Any]) -> list[Visualization]:
    """Generate task visualizations from a public SDK summary."""

    visuals: list[Visualization] = []
    for task in _list_value(summary.get("tasks")):
        if not isinstance(task, dict):
            continue
        model_params = _dict_value(task.get("model_params"))
        solver_result = _dict_value(task.get("solver_result"))
        if not model_params:
            visuals.append(_message_visualization(task, "缺少可视化参数。"))
            continue
        geometry = _dict_value(model_params.get("geometry"))
        geometry_type = str(geometry.get("type", "unknown")).lower()
        data = _task_field_data(task)
        if geometry_type == "beam":
            visuals.append(_beam_visualization(task, model_params, solver_result, data))
        elif geometry_type == "plate":
            visuals.append(_plate_visualization(task, model_params, solver_result, data))
        elif geometry_type == "solid":
            visuals.append(_solid_visualization(task, model_params, solver_result, data))
        else:
            visuals.append(_message_visualization(task, f"{geometry_type} 几何没有可用视图模板。"))
    return visuals


def _task_field_data(task: dict[str, Any]) -> "_FieldData":
    solver_result = _dict_value(task.get("solver_result"))
    mesh_result = _dict_value(task.get("mesh_result"))
    output_files = [Path(str(item)) for item in _list_value(solver_result.get("output_files"))]
    mesh_file = _optional_path(mesh_result.get("mesh_file")) or _optional_path(
        solver_result.get("mesh_file")
    )
    input_file = _first_existing_path(
        [*_paths_with_suffix(output_files, ".inp"), mesh_file],
    )
    frd_file = _first_existing_path(_paths_with_suffix(output_files, ".frd"))
    nodes = _parse_nodes(input_file) if input_file else {}
    elements = _parse_elements(input_file) if input_file else []
    displacements = _parse_frd_displacements(frd_file) if frd_file else {}
    return _FieldData(nodes=nodes, elements=elements, displacements=displacements)


@dataclass(frozen=True)
class _FieldData:
    nodes: dict[int, tuple[float, float, float]]
    elements: list[tuple[int, ...]]
    displacements: dict[int, tuple[float, float, float]]


def _beam_visualization(
    task: dict[str, Any],
    model_params: dict[str, Any],
    solver_result: dict[str, Any],
    data: _FieldData,
) -> Visualization:
    dimensions = _dimensions(model_params)
    length = _positive_float(dimensions.get("length"), 1000.0)
    predicted = _result_value(solver_result, ("tip_deflection", "tip_deflection_mm", "predicted"))
    nodes = data.nodes or _beam_fallback_nodes(length)
    displacements = data.displacements or _beam_fallback_displacements(nodes, predicted)
    points = sorted(nodes.items(), key=lambda item: item[1][0])
    max_deflection = max(
        (abs(displacements.get(node_id, (0.0, 0.0, 0.0))[1]) for node_id, _ in points),
        default=0.0,
    )
    deformation_scale = _deformation_scale(length, max_deflection, 0.28)

    def original_point(point: tuple[float, float, float]) -> tuple[float, float]:
        return _map_xy(point[0], 0.0, (0.0, length), (-length * 0.35, length * 0.35), 740, 260)

    def deformed_point(node_id: int, point: tuple[float, float, float]) -> tuple[float, float]:
        disp = displacements.get(node_id, (0.0, 0.0, 0.0))
        return _map_xy(
            point[0],
            disp[1] * deformation_scale,
            (0.0, length),
            (-length * 0.35, length * 0.35),
            740,
            260,
        )

    original = " ".join(_point_text(*original_point(point)) for _, point in points)
    deformed = " ".join(_point_text(*deformed_point(node_id, point)) for node_id, point in points)
    tip_x, tip_y = deformed_point(points[-1][0], points[-1][1])
    value_label = _metric_label(solver_result)
    svg = f"""
<svg viewBox="0 0 740 260" role="img" aria-label="{_esc(_title(task))} beam visualization" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="740" height="260" rx="10" fill="#f7f8fb"/>
  <text x="28" y="34" class="title">{_esc(_title(task))}</text>
  <text x="28" y="56" class="meta">B31 梁模型 · 蓝色为按位移放大的变形线</text>
  <line x1="72" y1="83" x2="72" y2="202" stroke="#374151" stroke-width="5"/>
  <polyline
    points="{original}"
    fill="none"
    stroke="#9ca3af"
    stroke-width="3"
    stroke-dasharray="8 8"/>
  <polyline
    points="{deformed}"
    fill="none"
    stroke="#2563eb"
    stroke-width="5"
    stroke-linecap="round"
    stroke-linejoin="round"/>
  <circle cx="{tip_x:.2f}" cy="{tip_y:.2f}" r="6" fill="#1d4ed8"/>
  <path
    d="M660 74 L660 128 M660 128 L650 112 M660 128 L670 112"
    fill="none"
    stroke="#dc2626"
    stroke-width="4"
    stroke-linecap="round"/>
  <text x="576" y="68" class="load">载荷方向</text>
  <rect x="28" y="208" width="684" height="34" rx="6" fill="#ffffff" stroke="#e5e7eb"/>
  <text x="44" y="230" class="metric">{_esc(value_label)}</text>
</svg>
"""
    return Visualization(
        task_id=str(task.get("task_id", "")),
        title=_title(task),
        kind="beam",
        svg=_style_svg(svg),
        caption="梁图使用求解器位移场绘制变形线；无位移场时使用主结果值生成等效形状。",
    )


def _plate_visualization(
    task: dict[str, Any],
    model_params: dict[str, Any],
    solver_result: dict[str, Any],
    data: _FieldData,
) -> Visualization:
    dimensions = _dimensions(model_params)
    length = _positive_float(dimensions.get("length"), 300.0)
    width = _positive_float(dimensions.get("width"), 200.0)
    nodes = data.nodes or _plate_fallback_nodes(length, width)
    displacements = data.displacements or _plate_fallback_displacements(
        nodes,
        _result_value(solver_result, ("center_deflection", "center_deflection_mm", "predicted")),
    )
    elements = [
        element for element in data.elements if len(element) == 4
    ] or _plate_fallback_elements()
    uz_values = [abs(displacements.get(node_id, (0.0, 0.0, 0.0))[2]) for node_id in nodes]
    max_uz = max(uz_values, default=0.0)
    polygons = []
    for element in elements[:1600]:
        if not all(node_id in nodes for node_id in element):
            continue
        intensity = sum(
            abs(displacements.get(node_id, (0.0, 0.0, 0.0))[2]) for node_id in element
        ) / max(
            len(element),
            1,
        )
        color = _heat_color(intensity / max_uz if max_uz > 0 else 0.0)
        points = " ".join(
            _point_text(
                *_map_xy(
                    nodes[node_id][0],
                    nodes[node_id][1],
                    (0.0, length),
                    (0.0, width),
                    740,
                    360,
                )
            )
            for node_id in element
        )
        polygons.append(
            f'<polygon points="{points}" fill="{color}" stroke="#e5e7eb" stroke-width="0.8"/>'
        )
    svg = f"""
<svg viewBox="0 0 740 360" role="img" aria-label="{_esc(_title(task))} plate visualization" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="740" height="360" rx="10" fill="#f7f8fb"/>
  <text x="28" y="34" class="title">{_esc(_title(task))}</text>
  <text x="28" y="56" class="meta">S4 板模型 · 颜色表示 |Uz| 位移幅值</text>
  <g>{"".join(polygons)}</g>
  <rect x="560" y="84" width="128" height="15" fill="url(#heat)"/>
  <text x="560" y="117" class="meta">低</text>
  <text x="664" y="117" class="meta">高</text>
  <defs>
    <linearGradient id="heat" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#dbeafe"/>
      <stop offset="50%" stop-color="#60a5fa"/>
      <stop offset="100%" stop-color="#dc2626"/>
    </linearGradient>
  </defs>
  <rect x="28" y="310" width="684" height="34" rx="6" fill="#ffffff" stroke="#e5e7eb"/>
  <text x="44" y="332" class="metric">{_esc(_metric_label(solver_result))}</text>
</svg>
"""
    return Visualization(
        task_id=str(task.get("task_id", "")),
        title=_title(task),
        kind="plate",
        svg=_style_svg(svg),
        caption="板图使用壳单元网格和 Uz 位移幅值生成云图式俯视图。",
    )


def _solid_visualization(
    task: dict[str, Any],
    model_params: dict[str, Any],
    solver_result: dict[str, Any],
    data: _FieldData,
) -> Visualization:
    dimensions = _dimensions(model_params)
    length = _positive_float(dimensions.get("length"), 200.0)
    width = _positive_float(dimensions.get("width"), 20.0)
    height = _positive_float(dimensions.get("height"), 20.0)
    nodes = data.nodes or _solid_fallback_nodes(length, width, height)
    displacements = data.displacements or _solid_fallback_displacements(
        nodes,
        _result_value(solver_result, ("axial_displacement", "axial_displacement_mm", "predicted")),
    )
    max_u1 = max(
        (abs(displacements.get(node_id, (0.0, 0.0, 0.0))[0]) for node_id in nodes),
        default=0.0,
    )
    deformation_scale = _deformation_scale(length, max_u1, 0.18)
    original = _solid_box_paths(nodes, {})
    deformed = _solid_box_paths(nodes, displacements, deformation_scale)
    svg = f"""
<svg viewBox="0 0 740 320" role="img" aria-label="{_esc(_title(task))} solid visualization" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="740" height="320" rx="10" fill="#f7f8fb"/>
  <text x="28" y="34" class="title">{_esc(_title(task))}</text>
  <text x="28" y="56" class="meta">C3D8R 实体模型 · 蓝色为轴向变形外形</text>
  <g opacity="0.7">{original}</g>
  <g>{deformed}</g>
  <path
    d="M640 126 L690 126 M690 126 L674 116 M690 126 L674 136"
    fill="none"
    stroke="#dc2626"
    stroke-width="4"
    stroke-linecap="round"/>
  <text x="606" y="106" class="load">端面载荷</text>
  <rect x="28" y="270" width="684" height="34" rx="6" fill="#ffffff" stroke="#e5e7eb"/>
  <text x="44" y="292" class="metric">{_esc(_metric_label(solver_result))}</text>
</svg>
"""
    return Visualization(
        task_id=str(task.get("task_id", "")),
        title=_title(task),
        kind="solid",
        svg=_style_svg(svg),
        caption="实体图使用节点位移绘制轴向变形外形；蓝色外框为放大后的变形状态。",
    )


def _message_visualization(task: dict[str, Any], message: str) -> Visualization:
    svg = f"""
<svg viewBox="0 0 740 220" role="img" aria-label="{_esc(_title(task))} message" xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="740" height="220" rx="10" fill="#f7f8fb"/>
  <text x="28" y="38" class="title">{_esc(_title(task))}</text>
  <rect x="28" y="72" width="684" height="94" rx="8" fill="#fff7ed" stroke="#fed7aa"/>
  <text x="48" y="124" class="metric">{_esc(message)}</text>
</svg>
"""
    return Visualization(
        task_id=str(task.get("task_id", "")),
        title=_title(task),
        kind="message",
        svg=_style_svg(svg),
        caption=message,
    )


def _style_svg(svg: str) -> str:
    style = """
<style>
  .title { font: 700 18px Arial, "Microsoft YaHei", sans-serif; fill: #111827; }
  .meta { font: 12px Arial, "Microsoft YaHei", sans-serif; fill: #6b7280; }
  .metric { font: 600 14px Arial, "Microsoft YaHei", sans-serif; fill: #1f2937; }
  .load { font: 12px Arial, "Microsoft YaHei", sans-serif; fill: #b91c1c; }
</style>
"""
    return svg.replace(">", f">{style}", 1).strip()


def _parse_nodes(path: Path) -> dict[int, tuple[float, float, float]]:
    nodes: dict[int, tuple[float, float, float]] = {}
    active = False
    for raw in _read_lines(path):
        line = raw.strip()
        upper = line.upper()
        if upper.startswith("*NODE"):
            active = True
            continue
        if active and line.startswith("*"):
            active = False
            continue
        if not active or not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 4:
            try:
                nodes[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))
            except ValueError:
                continue
    return nodes


def _parse_elements(path: Path) -> list[tuple[int, ...]]:
    elements: list[tuple[int, ...]] = []
    active = False
    for raw in _read_lines(path):
        line = raw.strip()
        upper = line.upper()
        if upper.startswith("*ELEMENT"):
            active = True
            continue
        if active and line.startswith("*"):
            active = False
            continue
        if not active or not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 3:
            try:
                elements.append(tuple(int(part) for part in parts[1:] if part))
            except ValueError:
                continue
    return elements


def _parse_frd_displacements(path: Path) -> dict[int, tuple[float, float, float]]:
    displacements: dict[int, tuple[float, float, float]] = {}
    mode: Optional[str] = None
    for line in _read_lines(path):
        if line.startswith(" -4  DISP"):
            mode = "disp"
            continue
        if line.startswith(" -4  ") and not line.startswith(" -4  DISP"):
            mode = None
            continue
        if line.startswith(" -3"):
            mode = None
            continue
        if not line.startswith(" -1") or mode != "disp":
            continue
        parsed = _parse_frd_data_line(line[3:])
        if parsed is None:
            continue
        node_id, values = parsed
        if len(values) >= 4:
            displacements[node_id] = (values[1], values[2], values[3])
    return displacements


def _parse_frd_data_line(text: str) -> tuple[int, list[float]] | None:
    node_text = text[:10].strip()
    data_text = text[10:]
    if node_text.isdigit():
        node_id = int(node_text)
    else:
        match = re.match(r"\s*(\d+)(?=[+-])", text)
        if not match:
            return None
        node_id = int(match.group(1))
        data_text = text[match.end() :]
    values = [float(token) for token in _FRD_FLOAT_PATTERN.findall(data_text)]
    return node_id, [float(node_id), *values]


def _solid_box_paths(
    nodes: dict[int, tuple[float, float, float]],
    displacements: dict[int, tuple[float, float, float]],
    deformation_scale: float = 1.0,
) -> str:
    points = _bbox_points(nodes, displacements, deformation_scale)
    projected = {key: _project_solid(*point) for key, point in points.items()}
    min_x = min(x for x, _ in projected.values())
    max_x = max(x for x, _ in projected.values())
    min_y = min(y for _, y in projected.values())
    max_y = max(y for _, y in projected.values())

    def fit(point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        sx = 92 + (x - min_x) / max(max_x - min_x, 1.0e-9) * 500
        sy = 90 + (y - min_y) / max(max_y - min_y, 1.0e-9) * 140
        return sx, sy

    edges = [
        ("000", "100"),
        ("100", "110"),
        ("110", "010"),
        ("010", "000"),
        ("001", "101"),
        ("101", "111"),
        ("111", "011"),
        ("011", "001"),
        ("000", "001"),
        ("100", "101"),
        ("110", "111"),
        ("010", "011"),
    ]
    color = "#2563eb" if displacements else "#9ca3af"
    dash = "" if displacements else ' stroke-dasharray="8 8"'
    lines = []
    for a, b in edges:
        x1, y1 = fit(projected[a])
        x2, y2 = fit(projected[b])
        lines.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{color}" stroke-width="3"{dash}/>'
        )
    return "".join(lines)


def _bbox_points(
    nodes: dict[int, tuple[float, float, float]],
    displacements: dict[int, tuple[float, float, float]],
    deformation_scale: float,
) -> dict[str, tuple[float, float, float]]:
    x_values = [point[0] for point in nodes.values()]
    y_values = [point[1] for point in nodes.values()]
    z_values = [point[2] for point in nodes.values()]
    min_x, max_x = min(x_values), max(x_values)
    min_y, max_y = min(y_values), max(y_values)
    min_z, max_z = min(z_values), max(z_values)

    def point(x: float, y: float, z: float) -> tuple[float, float, float]:
        if not displacements:
            return (x, y, z)
        node_id = min(
            nodes,
            key=lambda item: (
                (nodes[item][0] - x) ** 2 + (nodes[item][1] - y) ** 2 + (nodes[item][2] - z) ** 2
            ),
        )
        disp = displacements.get(node_id, (0.0, 0.0, 0.0))
        return (
            x + disp[0] * deformation_scale,
            y + disp[1] * deformation_scale,
            z + disp[2] * deformation_scale,
        )

    return {
        "000": point(min_x, min_y, min_z),
        "100": point(max_x, min_y, min_z),
        "110": point(max_x, max_y, min_z),
        "010": point(min_x, max_y, min_z),
        "001": point(min_x, min_y, max_z),
        "101": point(max_x, min_y, max_z),
        "111": point(max_x, max_y, max_z),
        "011": point(min_x, max_y, max_z),
    }


def _project_solid(x: float, y: float, z: float) -> tuple[float, float]:
    return (x + 0.45 * y, -0.32 * x + 0.72 * z)


def _map_xy(
    x: float,
    y: float,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    width: int,
    height: int,
) -> tuple[float, float]:
    margin_x = 72.0
    margin_y = 82.0
    inner_w = width - margin_x * 2
    inner_h = height - margin_y - 56.0
    sx = margin_x + (x - x_range[0]) / max(x_range[1] - x_range[0], 1.0e-9) * inner_w
    sy = margin_y + (1.0 - (y - y_range[0]) / max(y_range[1] - y_range[0], 1.0e-9)) * inner_h
    return sx, sy


def _point_text(x: float, y: float) -> str:
    return f"{x:.2f},{y:.2f}"


def _deformation_scale(length: float, max_displacement: float, ratio: float) -> float:
    if max_displacement <= 0:
        return 1.0
    return max(1.0, length * ratio / max_displacement)


def _heat_color(value: float) -> str:
    clamped = min(max(value, 0.0), 1.0)
    if clamped < 0.5:
        t = clamped / 0.5
        return _rgb(
            int(219 + (96 - 219) * t),
            int(234 + (165 - 234) * t),
            int(254 + (250 - 254) * t),
        )
    t = (clamped - 0.5) / 0.5
    return _rgb(
        int(96 + (220 - 96) * t),
        int(165 + (38 - 165) * t),
        int(250 + (38 - 250) * t),
    )


def _rgb(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _dimensions(model_params: dict[str, Any]) -> dict[str, Any]:
    return _dict_value(_dict_value(model_params.get("geometry")).get("dimensions"))


def _title(task: dict[str, Any]) -> str:
    task_id = str(task.get("task_id", "")).strip()
    title = str(task.get("title", "")).strip() or "仿真任务"
    return f"{task_id} · {title}" if task_id else title


def _metric_label(solver_result: dict[str, Any]) -> str:
    quantity = str(solver_result.get("quantity", "result"))
    predicted = _optional_float(solver_result.get("predicted"))
    reference = _optional_float(solver_result.get("reference"))
    relative_error = _optional_float(solver_result.get("relative_error"))
    unit = str(solver_result.get("unit", "")).strip()
    status = (
        "通过"
        if solver_result.get("passed") is True
        else str(solver_result.get("verification_status", "unverified"))
    )
    parts = [f"{quantity}: {_number_text(predicted)} {unit}".strip()]
    if reference is not None:
        parts.append(f"参考值 {_number_text(reference)} {unit}".strip())
    if relative_error is not None:
        parts.append(f"误差 {relative_error:.4%}")
    parts.append(f"状态 {status}")
    return " · ".join(parts)


def _result_value(solver_result: dict[str, Any], keys: tuple[str, ...]) -> float:
    values = _dict_value(solver_result.get("values"))
    for key in keys:
        for source in (solver_result, values):
            value = _optional_float(source.get(key))
            if value is not None:
                return value
            value = _optional_float(source.get(f"{key}_mm"))
            if value is not None:
                return value
    return 0.0


def _number_text(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value:.6g}"


def _beam_fallback_nodes(length: float) -> dict[int, tuple[float, float, float]]:
    return {index + 1: (length * index / 20.0, 0.0, 0.0) for index in range(21)}


def _beam_fallback_displacements(
    nodes: dict[int, tuple[float, float, float]],
    tip_deflection: float,
) -> dict[int, tuple[float, float, float]]:
    max_x = max(point[0] for point in nodes.values())
    sign = -1.0 if tip_deflection >= 0 else 1.0
    return {
        node_id: (0.0, sign * abs(tip_deflection) * (point[0] / max(max_x, 1.0e-9)) ** 2, 0.0)
        for node_id, point in nodes.items()
    }


def _plate_fallback_nodes(length: float, width: float) -> dict[int, tuple[float, float, float]]:
    nodes: dict[int, tuple[float, float, float]] = {}
    node_id = 1
    for j in range(11):
        for i in range(11):
            nodes[node_id] = (length * i / 10.0, width * j / 10.0, 0.0)
            node_id += 1
    return nodes


def _plate_fallback_elements() -> list[tuple[int, int, int, int]]:
    elements: list[tuple[int, int, int, int]] = []
    for j in range(10):
        for i in range(10):
            n1 = j * 11 + i + 1
            elements.append((n1, n1 + 1, n1 + 12, n1 + 11))
    return elements


def _plate_fallback_displacements(
    nodes: dict[int, tuple[float, float, float]],
    center_deflection: float,
) -> dict[int, tuple[float, float, float]]:
    x_values = [point[0] for point in nodes.values()]
    y_values = [point[1] for point in nodes.values()]
    min_x, max_x = min(x_values), max(x_values)
    min_y, max_y = min(y_values), max(y_values)
    return {
        node_id: (
            0.0,
            0.0,
            abs(center_deflection)
            * math.sin(math.pi * (point[0] - min_x) / max(max_x - min_x, 1.0e-9))
            * math.sin(math.pi * (point[1] - min_y) / max(max_y - min_y, 1.0e-9)),
        )
        for node_id, point in nodes.items()
    }


def _solid_fallback_nodes(
    length: float,
    width: float,
    height: float,
) -> dict[int, tuple[float, float, float]]:
    return {
        1: (0.0, 0.0, 0.0),
        2: (length, 0.0, 0.0),
        3: (length, width, 0.0),
        4: (0.0, width, 0.0),
        5: (0.0, 0.0, height),
        6: (length, 0.0, height),
        7: (length, width, height),
        8: (0.0, width, height),
    }


def _solid_fallback_displacements(
    nodes: dict[int, tuple[float, float, float]],
    axial_displacement: float,
) -> dict[int, tuple[float, float, float]]:
    max_x = max(point[0] for point in nodes.values())
    return {
        node_id: (abs(axial_displacement) * point[0] / max(max_x, 1.0e-9), 0.0, 0.0)
        for node_id, point in nodes.items()
    }


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []


def _first_existing_path(paths: Sequence[Optional[Path]]) -> Optional[Path]:
    for path in paths:
        if path is not None and path.exists():
            return path
    return None


def _paths_with_suffix(paths: list[Path], suffix: str) -> list[Path]:
    return [path for path in paths if path.suffix.lower() == suffix]


def _optional_path(value: Any) -> Optional[Path]:
    if not value:
        return None
    path = Path(str(value))
    return path if path.exists() else None


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _positive_float(value: Any, default: float) -> float:
    number = _optional_float(value)
    if number is None or number <= 0:
        return default
    return number


def _optional_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _esc(value: str) -> str:
    return html.escape(value, quote=True)

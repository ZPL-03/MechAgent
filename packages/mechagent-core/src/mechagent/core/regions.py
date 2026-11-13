"""案例和 CAD 适配器共享的区域名称规范。"""

from __future__ import annotations

REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "x_min": ("root", "fixed_end", "left_end"),
    "x_max": ("tip", "right_end", "loaded_end", "end_face", "free_end"),
    "z_max": ("top_surface", "top"),
    "z_min": ("bottom_surface", "bottom"),
}


def normalize_region_name(value: str) -> str:
    """去除首尾空白并统一区域名称中的大小写、连接符和空格。"""

    return value.strip().lower().replace("-", "_").replace(" ", "_")


def canonical_region_name(value: str) -> str:
    """返回区域名称对应的规范拓扑区域名称。"""

    normalized = normalize_region_name(value)
    for canonical, aliases in REGION_ALIASES.items():
        if normalized == canonical or normalized in aliases:
            return canonical
    return normalized


def region_family(value: str) -> tuple[str, ...]:
    """返回规范区域及其兼容别名。"""

    canonical = canonical_region_name(value)
    return (canonical, *REGION_ALIASES.get(canonical, ()))

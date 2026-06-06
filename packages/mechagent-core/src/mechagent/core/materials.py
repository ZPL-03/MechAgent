"""内置材料目录。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from mechagent.core.models import MaterialSpec


@dataclass(frozen=True)
class MaterialDefinition:
    """材料定义。

    Args:
        material_id: 材料编号。
        aliases: 自然语言别名。
        elastic_modulus_mpa: 弹性模量，单位为 MPa。
        poisson_ratio: 泊松比。
        density_tonne_per_mm3: 密度，单位为 tonne/mm^3。

    Returns:
        MaterialDefinition: 材料定义对象。

    Raises:
        TypeError: 当字段类型不匹配时由 dataclass 构造阶段抛出。

    Example:
        >>> BUILTIN_MATERIALS[0].material_id
        'steel'
    """

    material_id: str
    aliases: tuple[str, ...]
    elastic_modulus_mpa: float
    poisson_ratio: float
    density_tonne_per_mm3: float

    def to_spec(self) -> MaterialSpec:
        """转换为求解参数模型。

        Args:
            无。

        Returns:
            MaterialSpec: Pydantic 材料参数。

        Raises:
            pydantic.ValidationError: 当材料参数非法时抛出。

        Example:
            >>> BUILTIN_MATERIALS[0].to_spec().E
            210000.0
        """

        return MaterialSpec(
            E=self.elastic_modulus_mpa,
            nu=self.poisson_ratio,
            rho=self.density_tonne_per_mm3,
        )


BUILTIN_MATERIALS = (
    MaterialDefinition(
        material_id="steel",
        aliases=("钢", "steel", "q235", "q345"),
        elastic_modulus_mpa=210000.0,
        poisson_ratio=0.3,
        density_tonne_per_mm3=7.85e-9,
    ),
    MaterialDefinition(
        material_id="aluminum",
        aliases=("铝", "铝合金", "aluminum", "aluminium", "6061"),
        elastic_modulus_mpa=70000.0,
        poisson_ratio=0.33,
        density_tonne_per_mm3=2.7e-9,
    ),
)


def match_builtin_material(text: str) -> Optional[MaterialSpec]:
    """从自然语言文本匹配内置材料。

    Args:
        text: 用户自然语言文本。

    Returns:
        Optional[MaterialSpec]: 匹配成功返回材料参数，未匹配返回 None。

    Raises:
        pydantic.ValidationError: 当材料目录数据非法时抛出。

    Example:
        >>> match_builtin_material("材料钢").E
        210000.0
    """

    normalized = text.lower()
    for material in BUILTIN_MATERIALS:
        if any(alias in text or alias in normalized for alias in material.aliases):
            return material.to_spec()
    return None

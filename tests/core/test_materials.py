"""材料目录测试。"""

from __future__ import annotations

from mechagent.core.materials import BUILTIN_MATERIALS, match_builtin_material


def test_builtin_material_ids_are_unique() -> None:
    ids = [material.material_id for material in BUILTIN_MATERIALS]

    assert len(ids) == len(set(ids))


def test_match_builtin_material_supports_steel_alias() -> None:
    material = match_builtin_material("材料钢")

    assert material is not None
    assert material.E == 210000.0
    assert material.rho == 7.85e-9


def test_match_builtin_material_supports_aluminum_alias() -> None:
    material = match_builtin_material("6061 铝合金")

    assert material is not None
    assert material.nu == 0.33

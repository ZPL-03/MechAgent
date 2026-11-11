from pathlib import Path

from scripts.audit_python_dependencies import collect_requirements

ROOT = Path(__file__).resolve().parents[2]


def _names(requirements: list[str]) -> set[str]:
    names = set()
    for item in requirements:
        name = item.split("[", 1)[0]
        for operator in ("<", ">", "=", "!", "~", ";"):
            name = name.split(operator, 1)[0]
        names.add(name.lower())
    return names


def test_dependency_audit_excludes_local_distributions_and_collects_optional_deps() -> None:
    requirements = collect_requirements(ROOT)
    names = _names(requirements)

    assert "mechagent" not in names
    assert "mechagent-core" not in names
    assert "pip-audit" in names
    assert "mkdocs-material" in names
    assert requirements == sorted(requirements, key=lambda item: item.lower())


def test_dependency_audit_runtime_only_omits_optional_dependencies() -> None:
    requirements = collect_requirements(ROOT, include_optional=False)
    names = _names(requirements)

    assert "pip-audit" not in names
    assert "mkdocs-material" not in names
    assert "pydantic>=2,<3" in requirements

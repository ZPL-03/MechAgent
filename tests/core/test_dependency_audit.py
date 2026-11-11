import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import audit_python_dependencies
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


def test_dependency_audit_passes_output_path_to_pip_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    output = tmp_path / "audit.json"

    assert (
        audit_python_dependencies.audit(ROOT, include_optional=False, timeout=5, output=output) == 0
    )
    assert calls[0][-2:] == ["--output", str(output)]

"""项目脚本入口测试。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from scripts import (
    build_release_manifest,
    check_release_tag,
    check_wheel_install,
    generate_sbom,
    natural_language_cases,
    run_abaqus_multistep,
    run_backend_comparison,
    run_benchmarks,
    run_llm_smoke,
    run_natural_language_cases,
    sign_release,
    studio_http_smoke,
    verify_release,
)

from mechagent.config import MechAgentConfig, OutputSettings
from mechagent.core.validation import BenchmarkResult
from mechagent.evidence import verify_manifest


def test_studio_http_smoke_verifies_independent_process_and_writes_manifest(tmp_path: Path) -> None:
    result = studio_http_smoke.run_smoke(tmp_path / "studio-http")

    assert result["status"] == "passed"
    assert result["server_stopped"] is True
    assert result["manifest_errors"] == []
    assert verify_manifest(Path(result["manifest"])) == []


def test_release_tag_matches_both_package_versions(tmp_path: Path) -> None:
    for package in ("mechagent-core", "mechagent"):
        path = tmp_path / "packages" / package
        path.mkdir(parents=True)
        path.joinpath("pyproject.toml").write_text(
            '[project]\nname = "demo"\nversion = "1.2.3"\n', encoding="utf-8"
        )

    assert check_release_tag.validate_release_tag(tmp_path, "v1.2.3") == "1.2.3"
    with pytest.raises(ValueError, match="不一致"):
        check_release_tag.validate_release_tag(tmp_path, "v1.2.4")


def test_sign_release_requires_complete_keyless_identity(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"provenance": {"source": {"gitDirty": False}}}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="certificate-identity"):
        sign_release.main(
            [
                "--manifest",
                str(manifest),
                "--bundle",
                str(tmp_path / "bundle.json"),
            ]
        )


def test_verify_release_checks_artifact_digest_and_rejects_tampering(tmp_path: Path) -> None:
    artifact = tmp_path / "package.whl"
    artifact.write_bytes(b"package")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": "mechagent.release-manifest.v1",
                "version": "1.2.3",
                "provenance": {"source": {"gitDirty": False}},
                "artifacts": [
                    {
                        "path": artifact.name,
                        "size": artifact.stat().st_size,
                        "sha256": verify_release._sha256(artifact),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert verify_release.load_manifest(manifest)["version"] == "1.2.3"
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="摘要不匹配"):
        verify_release.load_manifest(manifest)


def test_verify_release_invokes_keyless_cosign_with_identity(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    artifact = tmp_path / "package.whl"
    artifact.write_bytes(b"package")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": "mechagent.release-manifest.v1",
                "version": "1.2.3",
                "provenance": {"source": {"gitDirty": False}},
                "artifacts": [
                    {
                        "path": artifact.name,
                        "size": artifact.stat().st_size,
                        "sha256": verify_release._sha256(artifact),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    bundle = tmp_path / "bundle.json"
    bundle.write_text("{}", encoding="utf-8")
    commands: list[list[str]] = []
    monkeypatch.setattr(shutil, "which", lambda _: "cosign.exe")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    verify_release.main(
        [
            "--manifest",
            str(manifest),
            "--bundle",
            str(bundle),
            "--certificate-identity",
            "https://github.com/example/repo/.github/workflows/release.yml@refs/tags/v1.2.3",
        ]
    )

    assert len(commands) == 1
    assert commands[0][1:3] == ["verify-blob", "--bundle"]
    assert "--certificate-identity" in commands[0]


def test_abaqus_multistep_summary_requires_all_steps_and_fields() -> None:
    result = {
        "success": True,
        "nodes": {"1": [0.0, 0.0, 0.0]},
        "fields": {
            "displacement": {"values": {"1": 1.0}},
            "stress": {"values": {"1@ip1": 1.0}},
            "strain": {"values": {"1@ip1": 1.0}},
            "volume": {"values": {"1": 1.0}},
            "energy": {"values": {"ALLIE": 1.0}},
        },
        "requested_fields": {
            "displacement": {"values": {"1": 1.0}},
            "stress_sxx": {"values": {"1@ip1": 1.0}},
            "strain": {"values": {"1@ip1": 1.0}},
            "volume": {"values": {"1": 1.0}},
            "energy": {"values": {"ALLIE": 1.0}},
        },
        "step_results": [
            {
                "fields": {
                    "displacement": {},
                    "stress_sxx": {},
                    "strain": {},
                    "volume": {},
                    "energy": {},
                }
            },
            {
                "fields": {
                    "displacement": {},
                    "stress_sxx": {},
                    "strain": {},
                    "volume": {},
                    "energy": {},
                }
            },
        ],
        "field_history": [{}, {}, {}, {}],
        "steps": [
            {
                "name": "step-1",
                "frames": [{}, {}],
                "fields": {
                    "U": {"values": {"1": 1.0}},
                    "S": {"values": {"1@ip1": 1.0}},
                    "E": {"values": {"1@ip1": 1.0}},
                    "EVOL": {"values": {"1": 1.0}},
                    "ENER": {"values": {"ALLIE": 1.0}},
                },
                "history": {"ALLIE": []},
            },
            {
                "name": "step-2",
                "frames": [{}, {}],
                "fields": {
                    "U": {"values": {"1": 1.0}},
                    "S": {"values": {"1@ip1": 1.0}},
                    "E": {"values": {"1@ip1": 1.0}},
                    "EVOL": {"values": {"1": 1.0}},
                    "ENER": {"values": {"ALLIE": 1.0}},
                },
                "history": {"ALLIE": []},
            },
        ],
        "output_files": ["case.com", "case.inp"],
        "field_json": "case.fields.json",
        "odb": "case.odb",
    }

    summary = run_abaqus_multistep._summary(result, "digest")

    assert summary["status"] == "passed"
    assert summary["input"] == "case.inp"
    assert summary["requested_field_counts"] == {
        "displacement": 1,
        "stress_sxx": 1,
        "strain": 1,
        "volume": 1,
        "energy": 1,
    }


def test_backend_comparison_script_writes_verifiable_manifest(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    def fake_run_case(*args: object, **_kwargs: object) -> dict[str, object]:
        return {"case_id": str(args[0]), "status": "passed"}

    monkeypatch.setattr(run_backend_comparison, "_run_case", fake_run_case)

    assert (
        run_backend_comparison.main(
            [
                "--case-id",
                "TC-01",
                "--calculix",
                "ccx",
                "--abaqus",
                "abaqus",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    manifest = tmp_path / "manifest.json"
    assert verify_manifest(manifest) == []
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "passed"


def test_run_benchmarks_script_uses_configured_output_dir(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "reports"
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        f"""
solver:
  calculix:
    path: custom-ccx
output:
  output_dir: {output_dir.as_posix()}
""".strip(),
        encoding="utf-8",
    )

    def fake_run_core_benchmarks(
        solver_path: str,
        work_dir: Path | None,
        num_cpus: int,
        timeout: int,
    ) -> list[BenchmarkResult]:
        assert solver_path == "custom-ccx"
        assert work_dir is None
        assert num_cpus == 1
        assert timeout == 3600
        return [
            BenchmarkResult(
                case_id="TC-XX",
                description="unit",
                predicted=1.0,
                reference=1.0,
                relative_error=0.0,
                tolerance=0.01,
                quantity="u",
                unit="mm",
                solver="unit",
            )
        ]

    monkeypatch.setattr(run_benchmarks, "run_core_benchmarks", fake_run_core_benchmarks)

    result = run_benchmarks.main(["--config", str(config_path)])

    assert result == 0
    assert (output_dir / "benchmark_results.json").exists()


def test_run_natural_language_cases_uses_configured_output_dir(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "runs"
    config = MechAgentConfig(output=OutputSettings(output_dir=output_dir))
    captured: dict[str, object] = {}

    class FakeResult:
        summary = {
            "tasks": [
                {
                    "model_params": {
                        "case_id": "STATIC-BEAM",
                        "geometry": {"type": "beam"},
                        "loads": [{"type": "force"}],
                    },
                    "solver_result": {"passed": True},
                }
            ],
            "report_path": "report.md",
        }

    class FakeAgent:
        def __init__(self, active_config: MechAgentConfig) -> None:
            captured["output_dir"] = active_config.output.output_dir
            self.config = active_config

        @classmethod
        def from_config(cls, _path: Path) -> "FakeAgent":
            return cls(config)

        def run(self, _request: str) -> FakeResult:
            return FakeResult()

    monkeypatch.setattr(run_natural_language_cases, "MechAgent", FakeAgent)
    monkeypatch.setattr(
        run_natural_language_cases,
        "STATIC_LANGUAGE_CASES",
        [
            natural_language_cases.StaticLanguageCase(
                case_id="SC-XX",
                request="unit",
                geometry_type="beam",
                load_type="force",
                model_case_id="STATIC-BEAM",
            )
        ],
    )

    result = run_natural_language_cases.main(["--config", str(tmp_path / "config.yaml")])

    assert result == 0
    assert captured["output_dir"] == output_dir / "natural_language_cases"


def test_run_llm_smoke_uses_configured_output_dir_and_validates_trace_summary(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_dir = tmp_path / "runs"
    report_path = output_dir / "llm_smoke" / "RUN" / "report.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("# unit\n\n## LLM 工程解释\n\n### 综合结论\n\n- ok\n", encoding="utf-8")
    config = MechAgentConfig(output=OutputSettings(output_dir=output_dir))
    captured: dict[str, object] = {}

    class FakeResult:
        summary = {
            "success": True,
            "work_dir": str(output_dir / "llm_smoke" / "RUN"),
            "report_path": str(report_path),
            "reporter_llm_trace": _trace_summary("ReporterAgent"),
            "tasks": [
                {
                    "task_id": "TASK_1",
                    "capability_id": "structural_static",
                    "planner_llm_trace": _trace_summary("Planner"),
                    "designer_llm_trace": _trace_summary("Designer"),
                    "mesh_llm_trace": _trace_summary("MeshAgent"),
                    "model_params": {"case_id": "STATIC-BEAM"},
                    "solver_result": {
                        "success": True,
                        "passed": True,
                        "verification_status": "passed",
                        "quantity": "tip_deflection",
                        "relative_error": 0.001,
                        "solver_llm_trace": _trace_summary("SolverAgent"),
                    },
                    "post_summary": {
                        "postproc_llm_trace": _trace_summary("PostProcAgent"),
                        "analyst_llm_trace": _trace_summary("AnalystAgent"),
                    },
                }
            ],
        }

    class FakeAgent:
        def __init__(self, active_config: MechAgentConfig) -> None:
            captured["output_dir"] = active_config.output.output_dir
            captured["llm_enabled"] = active_config.orchestrator.use_llm_agents
            self.config = active_config

        @classmethod
        def from_config(cls, _path: Path) -> "FakeAgent":
            return cls(config)

        def run(self, _request: str, use_llm_agents: bool | None = None) -> FakeResult:
            assert use_llm_agents is True
            return FakeResult()

    monkeypatch.setattr(run_llm_smoke, "MechAgent", FakeAgent)

    result = run_llm_smoke.main(["--config", str(tmp_path / "config.yaml")])

    assert result == 0
    assert captured["output_dir"] == output_dir / "llm_smoke"
    assert captured["llm_enabled"] is True


def test_run_llm_smoke_rejects_missing_agent_trace() -> None:
    summary = {
        "success": True,
        "reporter_llm_trace": _trace_summary("ReporterAgent"),
        "tasks": [
            {
                "task_id": "TASK_1",
                "planner_llm_trace": _trace_summary("Planner"),
                "designer_llm_trace": {"agent": "Designer", "used": False},
                "mesh_llm_trace": _trace_summary("MeshAgent"),
                "model_params": {"case_id": "STATIC-BEAM"},
                "solver_result": {
                    "success": True,
                    "passed": True,
                    "verification_status": "passed",
                    "solver_llm_trace": _trace_summary("SolverAgent"),
                },
                "post_summary": {
                    "postproc_llm_trace": _trace_summary("PostProcAgent"),
                    "analyst_llm_trace": _trace_summary("AnalystAgent"),
                },
            }
        ],
    }

    smoke = run_llm_smoke.evaluate_llm_smoke_summary(summary)

    assert smoke["passed"] is False
    assert any(
        item["name"] == "TASK_1.designer_llm_trace" and item["passed"] is False
        for item in smoke["checks"]
    )


def test_run_llm_smoke_accepts_noncritical_advisory_errors(tmp_path: Path) -> None:
    report_path = tmp_path / "RUN" / "report.md"
    report_path.parent.mkdir()
    report_path.write_text("# unit\n\n## LLM 工程解释\n\n### 综合结论\n\n- ok\n", encoding="utf-8")
    summary = {
        "success": True,
        "report_path": str(report_path),
        "reporter_llm_trace": _trace_summary("ReporterAgent"),
        "tasks": [
            {
                "task_id": "TASK_1",
                "planner_llm_trace": _trace_summary("Planner", error="请求超时"),
                "designer_llm_trace": _trace_summary("Designer"),
                "mesh_llm_trace": _trace_summary("MeshAgent", error="请求超时"),
                "model_params": {"case_id": "STATIC-BEAM"},
                "solver_result": {
                    "success": True,
                    "passed": True,
                    "verification_status": "passed",
                    "solver_llm_trace": _trace_summary("SolverAgent", error="请求超时"),
                },
                "post_summary": {
                    "postproc_llm_trace": _trace_summary("PostProcAgent", error="请求超时"),
                    "analyst_llm_trace": _trace_summary("AnalystAgent", error="请求超时"),
                },
            }
        ],
    }

    smoke = run_llm_smoke.evaluate_llm_smoke_summary(summary)

    assert smoke["passed"] is True
    assert any(
        item["name"] == "TASK_1.mesh_llm_trace_attempted" and item["passed"] is True
        for item in smoke["checks"]
    )


def test_check_wheel_install_finds_single_wheel(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "mechagent-0.1.0-py3-none-any.whl"
    wheel.write_text("unit", encoding="utf-8")

    assert check_wheel_install._find_single_wheel(dist, "mechagent-*.whl") == wheel


def test_check_wheel_install_rejects_missing_or_ambiguous_wheels(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()

    with pytest.raises(FileNotFoundError, match="数量必须为 1"):
        check_wheel_install._find_single_wheel(dist, "mechagent-*.whl")
    (dist / "mechagent-0.1.0-py3-none-any.whl").write_text("unit", encoding="utf-8")
    (dist / "mechagent-0.1.1-py3-none-any.whl").write_text("unit", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="数量必须为 1"):
        check_wheel_install._find_single_wheel(dist, "mechagent-*.whl")


def test_generate_sbom_contains_python_and_npm_packages(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lockfile = tmp_path / "apps/mechagent-studio/package-lock.json"
    lockfile.parent.mkdir(parents=True)
    lockfile.write_text(
        '{"packages": {"": {"name": "studio"}, '
        '"node_modules/@scope/widget": {"version": "1.2.3"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        generate_sbom,
        "_pip_packages",
        lambda: [
            generate_sbom._package(
                package_id="SPDXRef-PyPI-demo-1-0",
                name="demo",
                version="1.0",
                purl="pkg:pypi/demo@1.0",
                license_declared="MIT",
            )
        ],
    )

    document = generate_sbom.build_document(tmp_path)

    assert document["spdxVersion"] == "SPDX-2.3"
    packages = {item["name"]: item for item in document["packages"]}
    assert packages["demo"]["licenseDeclared"] == "MIT"
    assert packages["demo"]["licenseConcluded"] == "NOASSERTION"
    assert packages["@scope/widget"]["externalRefs"][0]["referenceLocator"] == (
        "pkg:npm/@scope/widget@1.2.3"
    )
    assert len(document["documentDescribes"]) == 2


def test_build_release_manifest_records_hashes_and_versions(tmp_path: Path) -> None:
    for distribution in ("mechagent-core", "mechagent"):
        package_dir = tmp_path / "packages" / distribution
        package_dir.mkdir(parents=True)
        (package_dir / "pyproject.toml").write_text(
            '[project]\nversion = "1.2.3"\n', encoding="utf-8"
        )
        dist_dir = package_dir / "dist"
        dist_dir.mkdir()
        normalized = distribution.replace("-", "_")
        (dist_dir / f"{normalized}-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
        (dist_dir / f"{normalized}-1.2.3.tar.gz").write_bytes(b"sdist")
    sbom = tmp_path / "dist" / "mechagent-sbom.spdx.json"
    sbom.parent.mkdir()
    sbom.write_text("{}", encoding="utf-8")

    document = build_release_manifest.build_document(tmp_path)

    assert document["schemaVersion"] == "mechagent.release-manifest.v1"
    assert document["version"] == "1.2.3"
    assert len(document["artifacts"]) == 5
    assert all(len(item["sha256"]) == 64 for item in document["artifacts"])
    assert document["provenance"]["schemaVersion"] == "mechagent.build-provenance.v1"
    assert document["provenance"]["source"]["gitCommit"] == document["gitCommit"]
    assert document["provenance"]["builder"]["pythonVersion"]


def test_build_release_manifest_rejects_missing_artifacts(tmp_path: Path) -> None:
    for distribution in ("mechagent-core", "mechagent"):
        package_dir = tmp_path / "packages" / distribution
        package_dir.mkdir(parents=True)
        (package_dir / "pyproject.toml").write_text(
            '[project]\nversion = "1.2.3"\n', encoding="utf-8"
        )

    with pytest.raises(FileNotFoundError, match="wheel 数量必须为 1"):
        build_release_manifest.build_document(tmp_path)


def test_check_wheel_install_import_check_validates_type_markers() -> None:
    assert "app_typed.exists()" in check_wheel_install._IMPORT_CHECK_CODE
    assert "core_typed.exists()" in check_wheel_install._IMPORT_CHECK_CODE


def test_check_wheel_install_import_check_validates_license_files() -> None:
    assert 'single_path("mechagent-*.dist-info")' in check_wheel_install._IMPORT_CHECK_CODE
    assert 'single_path("mechagent_core-*.dist-info")' in check_wheel_install._IMPORT_CHECK_CODE
    assert '"licenses" / "LICENSE"' in check_wheel_install._IMPORT_CHECK_CODE
    assert "Requires-Dist: mechagent-core=={version('mechagent-core')}" in (
        check_wheel_install._IMPORT_CHECK_CODE
    )
    assert "Requires-Dist: langgraph>=0.2" in check_wheel_install._IMPORT_CHECK_CODE
    assert "Requires-Dist: gmsh>=4.13" in check_wheel_install._IMPORT_CHECK_CODE
    assert "entry_points.txt" in check_wheel_install._IMPORT_CHECK_CODE
    assert "mechagent = mechagent.cli:app" in check_wheel_install._IMPORT_CHECK_CODE


def _trace_summary(agent: str, error: str | None = None) -> dict[str, object]:
    return {
        "agent": agent,
        "used": True,
        "error": error,
        "prompt_chars": 10,
        "response_chars": 0 if error else 10,
    }

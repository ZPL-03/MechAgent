"""仓库发布契约、文档链接与工具边界检查。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import yaml
from scripts.natural_language_cases import STATIC_LANGUAGE_CASES

from mechagent.config import KnowledgeSettings
from mechagent.core.factory import (
    registered_cad_kernels,
    registered_executors,
    registered_meshers,
    registered_solvers,
)
from mechagent.examples import all_examples

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DOCS = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    *sorted((ROOT / "docs").glob("*.md")),
    *sorted((ROOT / "packages").glob("*/README.md")),
    *sorted((ROOT / "knowledge/sources").glob("*.md")),
]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


@pytest.mark.parametrize("path", PUBLIC_DOCS, ids=lambda path: path.relative_to(ROOT).as_posix())
def test_public_markdown_links_resolve(path: Path) -> None:
    for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        target = target.strip().strip("<>")
        url = urlsplit(target)
        if url.scheme or target.startswith("#"):
            continue
        local = unquote(url.path)
        if local:
            assert (path.parent / local).exists(), f"{path.relative_to(ROOT)}: {target}"


@pytest.mark.parametrize("path", PUBLIC_DOCS, ids=lambda path: path.relative_to(ROOT).as_posix())
def test_public_docs_describe_facts_without_editing_narrative(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# ")
    assert not re.search(
        r"本次|此次|优化后|现在改为|我们完成了|新增|修改后|原来|补丁|过程性|TODO",
        text,
    )


def test_ignored_local_rules_are_not_release_documents() -> None:
    ignored = set(read(".gitignore").splitlines())
    assert {"AGENTS.md", "CLAUDE.md", ".env"} <= ignored
    assert not {"AGENTS.md", "CLAUDE.md"}.intersection(path.name for path in PUBLIC_DOCS)


def test_env_template_contains_public_placeholders() -> None:
    env = read(".env.example")
    for value in (
        "URL=https://example.com/v1",
        "API_KEY=replace-with-openai-compatible-api-key",
        "MODEL_NAME=replace-with-model-name",
        "CALCULIX_CCX=ccx",
    ):
        assert value in env


def test_package_source_has_no_local_installation_paths() -> None:
    for package in (ROOT / "packages").glob("*/src"):
        for path in package.rglob("*.py"):
            if path.name == "defaults.py":
                continue
            for marker in ("D:/Calculix", "D:/anaconda3", "ccx_MT.exe"):
                assert marker not in path.read_text(encoding="utf-8"), str(path)


def test_documentation_navigation_contains_every_topic_once() -> None:
    config = yaml.safe_load(read("mkdocs.yml"))

    def leaves(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [item for entry in value for item in leaves(entry)]
        if isinstance(value, dict):
            return [item for entry in value.values() for item in leaves(entry)]
        return []

    navigation = leaves(config["nav"])
    assert len(navigation) == len(set(navigation))
    assert set(navigation) == {path.name for path in (ROOT / "docs").glob("*.md")}


def test_tool_documentation_matches_builtin_registration() -> None:
    assert registered_solvers() == ("abaqus", "calculix")
    assert registered_meshers() == ("calculix-inp", "gmsh-cad-inp")
    assert registered_cad_kernels() == ("gmsh-occ",)
    assert registered_executors() == ("local",)
    architecture = read("docs/architecture.md")
    for name in (
        "register_solver()",
        "register_mesher()",
        "register_cad_kernel()",
        "register_executor()",
    ):
        assert name in architecture
    assert "没有独立工厂注册 API" in architecture
    assert "独立" in read("docs/solver_mesh.md")
    assert "Abaqus" in read("README.md")


def test_case_catalogue_matches_natural_language_validation_inputs() -> None:
    examples = all_examples()
    assert len(examples) == len(STATIC_LANGUAGE_CASES)
    assert [example.case_id for example in examples] == [
        case.case_id for case in STATIC_LANGUAGE_CASES
    ]
    assert len({example.case_id for example in examples}) == len(examples)
    assert all(example.request.strip() for example in examples)


def test_ci_contains_portable_gates_and_excludes_private_dependencies() -> None:
    workflow = read(".github/workflows/pr.yml")
    release_workflow = read(".github/workflows/release.yml")
    commands = [
        'python-version: "3.10"',
        'node-version: "22"',
        "npm --prefix apps/mechagent-studio ci --no-audit --no-fund",
        "npm --prefix apps/mechagent-studio run build",
        "npm --prefix apps/mechagent-studio test",
        "python scripts/check_env.py --profile portable",
        "python -m ruff format --check packages tests scripts",
        "python -m ruff check packages tests scripts",
        "python -m mypy packages scripts tests",
        'python -m pytest -m "not real_solver"',
        "python scripts/build_knowledge.py",
        "python scripts/index_knowledge.py",
        "python -m mechagent.cli config validate",
        "python -m pip check",
        "python -m build packages/mechagent-core",
        "python -m build packages/mechagent",
        "python scripts/check_wheel_install.py",
        "python scripts/studio_http_smoke.py --output-dir dist/studio-http-evidence",
        "python -m mkdocs build --strict",
        "python scripts/clean_artifacts.py",
    ]
    assert all(command in workflow for command in commands)
    assert "permissions:\n  contents: read" in workflow
    assert "sigstore/cosign-installer" in release_workflow
    assert "id-token: write" in release_workflow
    assert "--certificate-identity" in release_workflow
    assert "--root ." in release_workflow
    assert "scripts/verify_release.py" in release_workflow
    assert "gh attestation verify" in release_workflow
    assert "--signer-workflow" in release_workflow
    assert "--source-ref" in release_workflow
    for release_command in (
        "npm --prefix apps/mechagent-studio test",
        'python -m pytest -m "not real_solver"',
        "python scripts/studio_http_smoke.py --output-dir dist/studio-http-evidence",
        "python scripts/audit_python_dependencies.py --runtime-only",
        "python -m mkdocs build --strict",
    ):
        assert release_command in release_workflow
    for forbidden in (
        "D:/anaconda3",
        "self-hosted",
        "run_abaqus_smoke",
        "run_benchmarks.py",
        "run_natural_language_cases.py",
        "run_llm_smoke.py",
        "config validate --llm",
    ):
        assert forbidden not in workflow


def test_ci_actions_are_pinned_to_commit_shas() -> None:
    for relative in (".github/workflows/pr.yml", ".github/workflows/release.yml"):
        text = read(relative)
        references = re.findall(r"^\s*uses:\s+[^@\s]+@([^\s#]+)", text, flags=re.MULTILINE)
        assert references, relative
        assert all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in references), relative


def test_validation_guide_is_the_quality_command_reference() -> None:
    validation = read("docs/validation.md")
    for script in (
        "run_benchmarks.py",
        "run_natural_language_cases.py",
        "run_llm_smoke.py",
        "run_abaqus_smoke.py",
        "run_abaqus_multistep.py",
        "run_calculix_multistep.py",
        "audit_abaqus_license.py",
        "run_cad_topology_case.py",
        "run_backend_comparison.py",
        "compare_backends.py",
        "backup_studio.py",
        "restore_studio.py",
        "drill_studio_recovery.py",
        "check_s3_storage.py",
        "studio_http_smoke.py",
        "prune_artifacts.py",
        "check_wheel_install.py",
        "verify_release.py",
        "clean_artifacts.py",
    ):
        assert f"scripts/{script}" in validation
        assert (ROOT / "scripts" / script).is_file()
    for name in ("README.md", "CONTRIBUTING.md", "docs/local_setup.md"):
        assert "validation.md" in read(name)


def test_script_registry_matches_scripts_and_catalogue() -> None:
    registry_path = ROOT / "scripts" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry["schema"] == 1
    assert registry["root"] == "scripts"
    entries = registry["entries"]
    assert isinstance(entries, list) and entries
    paths = [entry["path"] for entry in entries]
    assert len(paths) == len(set(paths))
    actual = sorted(
        path.name for path in (ROOT / "scripts").glob("*.py") if path.name != "__init__.py"
    )
    assert sorted(paths) == actual
    for entry in entries:
        assert set(entry) == {
            "path",
            "category",
            "mutates_external_state",
            "real_solver",
            "description",
        }
        assert entry["category"]
        assert isinstance(entry["mutates_external_state"], bool)
        assert isinstance(entry["real_solver"], bool)
        assert entry["description"].strip()
    catalogue = read("docs/script_catalog.md")
    assert all(f"`{path}`" in catalogue for path in paths)


def test_public_knowledge_sources_are_configured_and_nonempty() -> None:
    config = yaml.safe_load(read("config/mechagent.yaml"))
    assert config["knowledge"]["raw_dir"] == "knowledge/sources"
    assert KnowledgeSettings().raw_dir == Path("knowledge/sources")
    for filename in ("static_structural_validation.md", "calculix_structural_workflow.md"):
        assert (ROOT / "knowledge/sources" / filename).stat().st_size > 0


def test_packages_publish_pep561_and_matching_licenses() -> None:
    license_text = read("LICENSE").strip()
    for name, module in (("mechagent", "mechagent"), ("mechagent-core", "mechagent/core")):
        package = ROOT / "packages" / name
        assert (package / "LICENSE").read_text(encoding="utf-8").strip() == license_text
        assert (package / "src" / module / "py.typed").is_file()
        metadata = (package / "pyproject.toml").read_text(encoding="utf-8")
        for value in (
            'license = "Apache-2.0"',
            'license-files = ["LICENSE"]',
            "Typing :: Typed",
            "Operating System :: OS Independent",
        ):
            assert value in metadata


def test_package_versions_and_core_dependency_agree() -> None:
    app = read("packages/mechagent/pyproject.toml")
    core = read("packages/mechagent-core/pyproject.toml")
    match = re.search(r'^version = "([^"]+)"', core, re.MULTILINE)
    assert match is not None
    assert f'version = "{match[1]}"' in app
    assert f'"mechagent-core=={match[1]}"' in app
    assert '"httpx>=0.27,<1"' in app


def test_studio_static_entry_references_existing_assets() -> None:
    static = ROOT / "packages/mechagent/src/mechagent/ui/static"
    html = (static / "index.html").read_text(encoding="utf-8")
    for asset in re.findall(r'(?:src|href)="(/(?:assets|brand)/[^"]+)"', html):
        assert (static / asset.lstrip("/")).is_file(), asset
    assert "figmacapture" not in html
    assert "mcp.figma.com" not in html
    assert (ROOT / "docs/assets/studio-geometry.png").is_file()
    assert (ROOT / "docs/assets/studio-workbench.png").is_file()


def test_frontend_network_and_theme_boundaries() -> None:
    source = ROOT / "apps/mechagent-studio/src"
    for path in source.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        if path.name != "api.ts":
            assert not re.search(r"\bfetch\s*\(", text), str(path)
    main = (source / "main.tsx").read_text(encoding="utf-8")
    assert "ThemeProvider" in main and "LocaleProvider" in main
    styles = (source / "styles.css").read_text(encoding="utf-8")
    assert "var(--color-" in styles
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", styles)
    assert "handleTabKeyDown" in (source / "lib/tabs.ts").read_text(encoding="utf-8")
    viewport = (source / "ThreeViewport.tsx").read_text(encoding="utf-8")
    assert 'controls.addEventListener("change", scheduleRender)' in viewport
    assert "const animate = () =>" not in viewport


def test_api_documentation_covers_real_studio_routes() -> None:
    server = read("packages/mechagent/src/mechagent/ui/server.py")
    guide = read("docs/studio_ui.md")
    routes = re.findall(r'@app\.(?:get|post)\("(/api/[^\"]+)"', server)
    assert routes
    assert all(route in guide for route in routes)

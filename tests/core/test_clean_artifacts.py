"""清理脚本边界测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest import MonkeyPatch
from scripts import clean_artifacts


def test_clean_artifacts_uses_repository_root(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (repo / "build").mkdir()
    (repo / "build" / "artifact.txt").write_text("x", encoding="utf-8")
    (repo / "case.frd").write_text("x", encoding="utf-8")
    (repo / ".playwright-mcp").mkdir()
    (repo / ".playwright-mcp" / "snapshot.yml").write_text("x", encoding="utf-8")
    (repo / "output" / "playwright").mkdir(parents=True)
    (repo / "output" / "playwright" / "screenshot.png").write_text("x", encoding="utf-8")
    (repo / "mechagent_output").mkdir()
    (repo / "mechagent_output" / "report.md").write_text("x", encoding="utf-8")
    (repo / "apps" / "mechagent-studio" / "node_modules").mkdir(parents=True)
    (repo / "apps" / "mechagent-studio" / "node_modules" / "cache.txt").write_text(
        "x",
        encoding="utf-8",
    )
    (repo / "knowledge" / "sources").mkdir(parents=True)
    (repo / "knowledge" / "sources" / "seed.md").write_text("x", encoding="utf-8")
    (repo / "knowledge" / "external").mkdir()
    (repo / "knowledge" / "external" / "generated.md").write_text("x", encoding="utf-8")
    (repo / "knowledge" / "index.jsonl").write_text("x", encoding="utf-8")
    (unrelated / "build").mkdir()
    (unrelated / "build" / "keep.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", repo)
    monkeypatch.chdir(unrelated)

    result = clean_artifacts.main()

    assert result == 0
    assert not (repo / "build").exists()
    assert not (repo / "case.frd").exists()
    assert not (repo / ".playwright-mcp").exists()
    assert not (repo / "output").exists()
    assert not (repo / "mechagent_output").exists()
    assert not (repo / "apps" / "mechagent-studio" / "node_modules").exists()
    assert not (repo / "knowledge" / "external").exists()
    assert not (repo / "knowledge" / "index.jsonl").exists()
    assert (repo / "knowledge" / "sources" / "seed.md").exists()
    assert (unrelated / "build" / "keep.txt").exists()


def test_clean_artifacts_rejects_paths_outside_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError, match="不在仓库目录内"):
        clean_artifacts._ensure_inside_repo(outside)


def test_clean_artifacts_scan_tolerates_vanished_paths(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    cache = repo / ".pytest_cache"
    cache.mkdir()

    class VanishingRoot:
        def rglob(self, _pattern: str):
            yield cache
            raise FileNotFoundError("vanished")

    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", VanishingRoot())

    assert list(clean_artifacts._iter_repo_paths(".pytest_cache")) == [cache]

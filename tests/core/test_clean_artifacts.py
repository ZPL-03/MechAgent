"""清理脚本边界测试。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from scripts import clean_artifacts

from mechagent.runtime.store import JobStore


def test_cleanup_refuses_nonterminal_persistent_jobs(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(tmp_path / "mechagent_output/.studio/jobs.sqlite3")
    store.submit("求解请求", False, config, max_queued=1)
    with pytest.raises(RuntimeError, match="非终态"):
        clean_artifacts.main(["--include-runs"])
    assert store.database.exists()


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
    (repo / ".playwright-cli").mkdir()
    (repo / ".playwright-cli" / "session.json").write_text("x", encoding="utf-8")
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
    (repo / ".cache").mkdir()
    (repo / ".cache" / "tool.bin").write_bytes(b"x")
    (repo / ".coverage").write_text("x", encoding="utf-8")
    (repo / "apps" / "mechagent-studio" / ".vite").mkdir(parents=True)
    (repo / "apps" / "mechagent-studio" / ".vite" / "cache").write_text("x", encoding="utf-8")
    (repo / "knowledge" / "sources").mkdir(parents=True)
    (repo / "knowledge" / "sources" / "seed.md").write_text("x", encoding="utf-8")
    (repo / "knowledge" / "external").mkdir()
    (repo / "knowledge" / "external" / "generated.md").write_text("x", encoding="utf-8")
    (repo / "knowledge" / "index.jsonl").write_text("x", encoding="utf-8")
    (unrelated / "build").mkdir()
    (unrelated / "build" / "keep.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", repo)
    monkeypatch.chdir(unrelated)

    result = clean_artifacts.main(["--include-runs"])

    assert result == 0
    assert not (repo / "build").exists()
    assert not (repo / "case.frd").exists()
    assert not (repo / ".playwright-cli").exists()
    assert not (repo / ".playwright-mcp").exists()
    assert not (repo / "output").exists()
    assert not (repo / "mechagent_output").exists()
    assert not (repo / "apps" / "mechagent-studio" / "node_modules").exists()
    assert not (repo / ".cache").exists()
    assert not (repo / ".coverage").exists()
    assert not (repo / "apps" / "mechagent-studio" / ".vite").exists()
    assert not (repo / "knowledge" / "external").exists()
    assert not (repo / "knowledge" / "index.jsonl").exists()
    assert (repo / "knowledge" / "sources" / "seed.md").exists()
    assert (unrelated / "build" / "keep.txt").exists()


def test_clean_artifacts_rejects_paths_outside_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError, match="不在仓库子目录内"):
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
        def rglob(self, _pattern: str) -> Iterator[Path]:
            yield cache
            raise FileNotFoundError("vanished")

    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", VanishingRoot())

    assert list(clean_artifacts._iter_repo_paths(".pytest_cache")) == [cache]


def test_default_cleanup_preserves_runs(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", tmp_path)
    output = tmp_path / "mechagent_output"
    output.mkdir()
    (output / "evidence.dat").write_text("result")
    assert clean_artifacts.main([]) == 0
    assert (output / "evidence.dat").exists()


def test_cleanup_removes_common_cache_files_and_dry_run_is_non_destructive(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", tmp_path)
    cache_file = tmp_path / ".eslintcache"
    cache_file.write_text("cache", encoding="utf-8")
    pyc_file = tmp_path / "module.pyc"
    pyc_file.write_bytes(b"cache")
    coverage_fragment = tmp_path / ".coverage.12345"
    coverage_fragment.write_text("cache", encoding="utf-8")
    upload_fragment = tmp_path / ".upload.12345.tmp"
    upload_fragment.write_bytes(b"cache")

    assert clean_artifacts.main(["--dry-run"]) == 0
    assert cache_file.exists()
    assert pyc_file.exists()
    output = capsys.readouterr().out
    assert str(cache_file) in output
    assert str(pyc_file) in output
    assert str(tmp_path / "site") not in output

    assert clean_artifacts.main([]) == 0
    assert not cache_file.exists()
    assert not pyc_file.exists()
    assert not coverage_fragment.exists()
    assert not upload_fragment.exists()


def test_explicit_studio_runtime_cleanup_preserves_formal_evidence(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", tmp_path)
    runtime = tmp_path / "mechagent_output" / ".studio"
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(runtime / "jobs.sqlite3")
    job = store.submit("finished", False, config, max_queued=1)
    store.cancel(job["job_id"])
    formal = tmp_path / "mechagent_output" / "benchmarks" / "manifest.json"
    formal.parent.mkdir(parents=True)
    formal.write_text('{"status":"passed"}', encoding="utf-8")

    assert clean_artifacts.main(["--include-studio-runtime"]) == 0

    assert not runtime.exists()
    assert formal.is_file()


def test_studio_runtime_cleanup_refuses_active_jobs(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    store = JobStore(tmp_path / "mechagent_output/.studio/jobs.sqlite3")
    store.submit("active", False, config, max_queued=1)

    with pytest.raises(RuntimeError, match="非终态"):
        clean_artifacts.main(["--include-studio-runtime"])

    assert store.database.exists()


def test_studio_runtime_cleanup_refuses_corrupt_database(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", tmp_path)
    runtime = tmp_path / "mechagent_output" / ".studio"
    runtime.mkdir(parents=True)
    database = runtime / "jobs.sqlite3"
    database.write_bytes(b"corrupt")

    with pytest.raises(RuntimeError, match="无法读取作业数据库"):
        clean_artifacts.main(["--include-studio-runtime"])

    assert database.exists()


def test_cleanup_preserves_tracked_files(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", tmp_path)
    build = tmp_path / "build"
    build.mkdir()
    formal = build / "formal.dat"
    formal.write_text("keep")
    monkeypatch.setattr(clean_artifacts, "_tracked_paths", lambda: {formal})
    assert clean_artifacts.main(["--include-runs"]) == 0
    assert formal.exists()


def test_cleanup_rejects_locked_runs_before_deleting(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(clean_artifacts, "REPO_ROOT", tmp_path)
    (tmp_path / "build").mkdir()
    (tmp_path / "job.lck").touch()
    with pytest.raises(RuntimeError, match="求解锁"):
        clean_artifacts.main(["--include-runs"])
    assert (tmp_path / "build").exists()

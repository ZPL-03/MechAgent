"""环境检查脚本测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest import CaptureFixture, MonkeyPatch
from scripts import check_env


def test_python_path_comparison_normalizes_separators() -> None:
    assert check_env._same_path(
        Path("D:/anaconda3/envs/AGENT/python.exe"),
        Path(r"D:\anaconda3\envs\AGENT\python.exe"),
    )


def test_check_python_requires_expected_executor() -> None:
    result = check_env._check_python()

    assert result["version_ok"] is True
    assert result["executable_ok"] is True
    assert result["ok"] is True
    assert result["profile"] == "local"


def test_check_python_portable_profile_allows_current_executor() -> None:
    result = check_env._check_python("portable")

    assert result["version_ok"] is True
    assert result["executable_ok"] is True
    assert result["ok"] is True
    assert result["profile"] == "portable"


def test_env_check_requires_all_llm_keys_when_requested(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("URL", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    (tmp_path / ".env").write_text("URL=https://example.com/v1\nAPI_KEY=key\n", encoding="utf-8")

    result = check_env._check_env_file(require_llm=True)

    assert result["has_env_file"] is True
    assert result["keys"]["MODEL_NAME"] is False
    assert result["keys_ok"] is False
    assert result["required_ok"] is False


def test_env_check_allows_missing_llm_keys_by_default(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("URL", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)

    result = check_env._check_env_file()

    assert result["has_env_file"] is False
    assert result["keys_ok"] is False
    assert result["required_ok"] is True


def test_env_check_reports_calculix_ccx_without_requiring_it(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("URL", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("CALCULIX_CCX", raising=False)
    (tmp_path / ".env").write_text("CALCULIX_CCX=D:/Calculix/ccx.exe\n", encoding="utf-8")

    result = check_env._check_env_file()

    assert result["tool_keys"]["CALCULIX_CCX"] is True
    assert result["keys_ok"] is False
    assert result["required_ok"] is True


def test_configured_calculix_path_reads_yaml_and_expands_env(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "ccx.exe"
    executable.write_text("", encoding="utf-8")
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        "solver:\n  calculix:\n    path: ${CCX_HOME}/ccx.exe\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CCX_HOME", bin_dir.as_posix())

    configured = check_env._configured_calculix_path(config_path)

    assert configured == executable


def test_configured_calculix_path_uses_default_when_env_missing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        "solver:\n  calculix:\n    path: ${CALCULIX_CCX:-ccx}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CALCULIX_CCX", raising=False)

    configured = check_env._configured_calculix_path(config_path)

    assert configured == Path("ccx")


def test_executable_check_uses_configured_calculix_path(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    executable = tmp_path / "ccx.exe"
    executable.write_text("", encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "mechagent.yaml").write_text(
        f"solver:\n  calculix:\n    path: {executable.as_posix()}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = check_env._check_executables()

    assert result["configured_ccx"] == str(executable)
    assert result["configured_ccx_exists"] is True
    assert result["configured_ccx_available"] is True
    assert result["config_path_exists"] is True


def test_configured_calculix_path_reports_missing_config(tmp_path: Path) -> None:
    assert check_env._configured_calculix_path(tmp_path / "missing.yaml") is None


def test_check_env_help_exits_without_running_checks(
    capsys: CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        check_env.main(["--help"])

    assert exc_info.value.code == 0
    assert "--config" in capsys.readouterr().out


def test_main_uses_config_argument_without_requiring_llm(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    executable = tmp_path / "ccx.exe"
    executable.write_text("", encoding="utf-8")
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        f"solver:\n  calculix:\n    path: {executable.as_posix()}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("URL", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)

    result = check_env.main(["--config", str(config_path)])

    assert result == 0
    assert '"llm_required": false' in capsys.readouterr().out


def test_main_can_require_llm_keys(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    executable = tmp_path / "ccx.exe"
    executable.write_text("", encoding="utf-8")
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        f"solver:\n  calculix:\n    path: {executable.as_posix()}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("URL", "https://example.com/v1")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.delenv("MODEL_NAME", raising=False)

    result = check_env.main(["--config", str(config_path), "--require-llm"])

    assert result == 1
    output = capsys.readouterr().out
    assert '"llm_required": true' in output
    assert '"MODEL_NAME": false' in output


def test_main_portable_profile_does_not_require_local_solver_or_env(
    tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    config_path = tmp_path / "mechagent.yaml"
    config_path.write_text(
        "solver:\n  calculix:\n    path: missing-ccx\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("URL", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)

    result = check_env.main(["--config", str(config_path), "--profile", "portable"])

    assert result == 0
    output = capsys.readouterr().out
    assert '"profile": "portable"' in output
    assert '"configured_ccx_available": false' in output
    assert '"llm_required": false' in output

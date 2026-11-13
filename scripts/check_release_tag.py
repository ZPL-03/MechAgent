"""校验发布 tag 与两个 Python 包版本一致。"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared tomli compatibility package.
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def validate_release_tag(root: Path, tag: str) -> str:
    normalized_tag = tag.strip()
    if not normalized_tag.startswith("v") or len(normalized_tag) == 1:
        raise ValueError("发布 tag 必须使用 v<版本> 格式。")
    version = normalized_tag[1:]
    versions = {
        name: _project_version(root / "packages" / name / "pyproject.toml")
        for name in ("mechagent-core", "mechagent")
    }
    if len(set(versions.values())) != 1:
        raise ValueError("mechagent 与 mechagent-core 的版本必须一致。")
    expected = next(iter(versions.values()))
    if version != expected:
        raise ValueError(f"发布 tag {normalized_tag} 与包版本 {expected} 不一致。")
    return expected


def _project_version(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as stream:
        payload = tomllib.load(stream)
    project = payload.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise ValueError(f"无法读取包版本：{path}")
    return str(project["version"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    version = validate_release_tag(args.root.resolve(), args.tag)
    print(f"release tag validated: v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

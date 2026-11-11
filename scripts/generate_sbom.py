"""生成 MechAgent 的 SPDX 2.3 软件物料清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

SPDX_VERSION = "SPDX-2.3"
_SPDX_LICENSES = {
    "AGPL-3.0-only",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "CC0-1.0",
    "GPL-2.0-only",
    "GPL-3.0-only",
    "ISC",
    "LGPL-2.1-only",
    "LGPL-3.0-only",
    "MIT",
    "MPL-2.0",
    "PSF-2.0",
    "Unlicense",
}


def _normalize_license(value: str) -> str:
    """只保留可确认的 SPDX 标识，未知元数据保持 NOASSERTION。"""

    candidate = value.strip()
    if candidate in _SPDX_LICENSES:
        return candidate
    aliases = {
        "apache license 2.0": "Apache-2.0",
        "apache 2.0": "Apache-2.0",
        "mit license": "MIT",
        "mozilla public license 2.0": "MPL-2.0",
        "python software foundation license": "PSF-2.0",
    }
    return aliases.get(candidate.lower(), "NOASSERTION")


def _spdx_id(prefix: str, name: str, version: str) -> str:
    safe = "".join(char if char.isalnum() else "-" for char in f"{name}-{version}")
    return f"SPDXRef-{prefix}-{safe}"


def _package(
    *,
    package_id: str,
    name: str,
    version: str,
    purl: str,
    license_declared: str = "NOASSERTION",
) -> dict[str, Any]:
    return {
        "SPDXID": package_id,
        "name": name,
        "versionInfo": version,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        # 依赖元数据只提供声明许可证；未执行源码扫描时不能推断结论许可证。
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": _normalize_license(license_declared),
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": purl,
            }
        ],
    }


def _pip_packages() -> list[dict[str, Any]]:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "inspect"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    payload = json.loads(completed.stdout)
    packages: list[dict[str, Any]] = []
    for item in payload.get("installed", []):
        metadata = item.get("metadata", {})
        name = str(metadata.get("name", "")).strip()
        version = str(metadata.get("version", "")).strip()
        if not name or not version:
            continue
        license_declared = str(metadata.get("license", "")).strip() or "NOASSERTION"
        packages.append(
            _package(
                package_id=_spdx_id("PyPI", name, version),
                name=name,
                version=version,
                purl=f"pkg:pypi/{quote(name.lower())}@{quote(version)}",
                license_declared=license_declared,
            )
        )
    return packages


def _npm_packages(lockfile: Path) -> list[dict[str, Any]]:
    payload = json.loads(lockfile.read_text(encoding="utf-8"))
    packages: list[dict[str, Any]] = []
    for path, item in payload.get("packages", {}).items():
        if not path or not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        if not name:
            marker = "node_modules/"
            name = path.rsplit(marker, 1)[-1] if marker in path else ""
        version = str(item.get("version", "")).strip()
        if not name or not version:
            continue
        license_declared = str(item.get("license", "")).strip() or "NOASSERTION"
        packages.append(
            _package(
                package_id=_spdx_id("NPM", name, version),
                name=name,
                version=version,
                purl=f"pkg:npm/{quote(name, safe='@/')}@{quote(version)}",
                license_declared=license_declared,
            )
        )
    return packages


def build_document(root: Path) -> dict[str, Any]:
    """读取当前 Python 环境和前端 lockfile，构造 SPDX 文档。"""

    package_lock = root / "apps" / "mechagent-studio" / "package-lock.json"
    packages = _pip_packages()
    if package_lock.is_file():
        packages.extend(_npm_packages(package_lock))
    packages.sort(key=lambda item: (item["name"].lower(), item["versionInfo"], item["SPDXID"]))
    coordinates = "\n".join(f"{item['name']}@{item['versionInfo']}" for item in packages).encode(
        "utf-8"
    )
    digest = hashlib.sha256(coordinates).hexdigest()[:20]
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0") or 0)
    created = datetime.fromtimestamp(epoch or datetime.now(timezone.utc).timestamp(), timezone.utc)
    return {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "MechAgent SBOM",
        "documentNamespace": f"https://github.com/ZPL-03/MechAgent/sbom/{digest}",
        "creationInfo": {
            "created": created.isoformat().replace("+00:00", "Z"),
            "creators": ["Tool: MechAgent scripts/generate_sbom.py"],
        },
        "documentComment": ("许可证字段缺失时保留 NOASSERTION；发布前必须完成许可证人工审计。"),
        "packages": packages,
        "documentDescribes": [item["SPDXID"] for item in packages],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1], help="项目根目录"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("dist/mechagent-sbom.spdx.json"), help="输出文件"
    )
    args = parser.parse_args(argv)
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_document(args.root), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

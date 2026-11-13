"""校验发布清单中的文件摘要，并验证 cosign 签名。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def load_manifest(
    path: Path,
    *,
    root: Path | None = None,
    expected_commit: str | None = None,
    expected_version: str | None = None,
) -> dict[str, Any]:
    """读取并校验发布清单记录的所有本地 artifact。

    清单中的 artifact 路径相对于构建根目录；未显式提供根目录时，兼容性地
    使用清单所在目录。发布工作流必须传入仓库根目录。
    """

    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"发布清单无法读取: {path}") from exc
    if not isinstance(document, dict) or document.get("schemaVersion") != (
        "mechagent.release-manifest.v1"
    ):
        raise ValueError("不支持的发布清单版本。")
    provenance = document.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("发布清单缺少 provenance。")
    source = provenance.get("source")
    if not isinstance(source, dict) or source.get("gitDirty") is not False:
        raise ValueError("发布清单要求干净且可识别的 Git 源状态。")
    if expected_commit is not None:
        actual_commit = source.get("gitCommit") or document.get("gitCommit")
        if actual_commit != expected_commit:
            raise ValueError("发布清单 Git 提交与期望提交不一致。")
    if expected_version is not None and document.get("version") != expected_version:
        raise ValueError("发布清单版本与期望版本不一致。")
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("发布清单必须包含 artifact。")
    resolved_root = (root or path.parent).resolve()
    seen: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise ValueError("发布清单的 artifact 记录格式无效。")
        relative = item.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or relative in seen
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ValueError(f"发布清单包含无效或重复路径: {relative!r}")
        candidate = (resolved_root / relative).resolve()
        if not candidate.is_relative_to(resolved_root) or not candidate.is_file():
            raise FileNotFoundError(f"发布清单 artifact 不存在或越界: {relative}")
        size = item.get("size")
        digest = item.get("sha256")
        if (
            not isinstance(size, int)
            or size < 0
            or not isinstance(digest, str)
            or not _SHA256.fullmatch(digest)
        ):
            raise ValueError(f"发布清单 artifact 元数据无效: {relative}")
        actual_digest = _sha256(candidate)
        if candidate.stat().st_size != size or actual_digest != digest:
            raise ValueError(f"发布清单 artifact 摘要不匹配: {relative}")
        seen.add(relative)
    return document


def verify_signature(
    manifest: Path,
    *,
    signature: Path | None = None,
    bundle: Path | None = None,
    key: Path | None = None,
    certificate_identity: str | None = None,
    certificate_oidc_issuer: str | None = None,
    cosign: str = "cosign",
) -> None:
    """使用受控密钥或 OIDC bundle 验证清单签名。"""

    if key is not None:
        if not key.is_file():
            raise FileNotFoundError(key)
        if (
            signature is None
            or bundle is not None
            or certificate_identity is not None
            or certificate_oidc_issuer is not None
        ):
            raise ValueError("密钥模式必须只提供 --key 和 --signature。")
    elif bundle is None or not certificate_identity or signature is not None:
        raise ValueError("keyless 模式必须只提供 --bundle 和 --certificate-identity。")
    signed_artifact = signature if signature is not None else bundle
    if signed_artifact is None:
        raise ValueError("必须提供签名文件或签名 bundle。")
    if not signed_artifact.is_file():
        raise FileNotFoundError(signed_artifact)
    executable = shutil.which(cosign) or (str(Path(cosign)) if Path(cosign).is_file() else None)
    if executable is None:
        raise RuntimeError("未找到 cosign；发布验证不允许无签名降级。")
    if key is not None:
        command = [
            executable,
            "verify-blob",
            "--key",
            str(key),
            "--signature",
            str(signature),
            str(manifest),
        ]
    else:
        identity = certificate_identity
        if not identity:
            raise ValueError("keyless 模式必须提供证书身份。")
        command = [
            executable,
            "verify-blob",
            "--bundle",
            str(bundle),
            "--certificate-identity",
            identity,
            "--certificate-oidc-issuer",
            certificate_oidc_issuer or "https://token.actions.githubusercontent.com",
            str(manifest),
        ]
    subprocess.run(command, check=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--signature", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--key", type=Path)
    parser.add_argument("--certificate-identity")
    parser.add_argument("--certificate-oidc-issuer")
    parser.add_argument("--cosign", default="cosign")
    parser.add_argument(
        "--root",
        type=Path,
        help="清单 artifact 路径的构建根目录；默认使用清单所在目录。",
    )
    parser.add_argument("--expected-commit", help="要求清单绑定到指定 Git 提交。")
    parser.add_argument("--expected-version", help="要求清单版本等于指定值。")
    args = parser.parse_args(argv)
    document = load_manifest(
        args.manifest,
        root=args.root,
        expected_commit=args.expected_commit,
        expected_version=args.expected_version,
    )
    verify_signature(
        args.manifest,
        signature=args.signature,
        bundle=args.bundle,
        key=args.key,
        certificate_identity=args.certificate_identity,
        certificate_oidc_issuer=args.certificate_oidc_issuer,
        cosign=args.cosign,
    )
    print(
        json.dumps(
            {
                "manifest": str(args.manifest),
                "sha256": _sha256(args.manifest),
                "version": document["version"],
                "artifact_count": len(document["artifacts"]),
                "signature": str(args.signature or args.bundle),
                "verified": True,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""使用 cosign 对发布清单签名并立即验证。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_release import load_manifest  # noqa: E402


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
    args = parser.parse_args(argv)
    if not args.manifest.is_file():
        raise FileNotFoundError(args.manifest)
    if args.key is not None and not args.key.is_file():
        raise FileNotFoundError(args.key)
    if args.key is not None and args.certificate_identity:
        raise ValueError("--key 与 keyless 证书身份参数不能同时使用。")
    if args.key is not None and not args.signature:
        raise ValueError("密钥模式必须提供 --signature。")
    if args.key is None and (not args.bundle or not args.certificate_identity):
        raise ValueError("keyless 模式必须同时提供 --certificate-identity 和 --bundle。")
    document = load_manifest(args.manifest, root=args.root)
    provenance = document.get("provenance", {}).get("source", {})
    if provenance.get("gitDirty") is not False:
        raise ValueError("发布清单要求干净且可识别的 Git 源状态。")
    executable = shutil.which(args.cosign) or (
        str(Path(args.cosign)) if Path(args.cosign).is_file() else None
    )
    if executable is None:
        raise RuntimeError("未找到 cosign；签名发布不允许无签名降级。")
    output = args.signature or args.bundle
    assert output is not None
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.key is not None:
        subprocess.run(
            [
                executable,
                "sign-blob",
                "--key",
                str(args.key),
                "--output-signature",
                str(args.signature),
                str(args.manifest),
            ],
            check=True,
        )
        subprocess.run(
            [
                executable,
                "verify-blob",
                "--key",
                str(args.key),
                "--signature",
                str(args.signature),
                str(args.manifest),
            ],
            check=True,
        )
    else:
        issuer = args.certificate_oidc_issuer or "https://token.actions.githubusercontent.com"
        subprocess.run(
            [
                executable,
                "sign-blob",
                "--yes",
                "--bundle",
                str(args.bundle),
                str(args.manifest),
            ],
            check=True,
        )
        subprocess.run(
            [
                executable,
                "verify-blob",
                "--bundle",
                str(args.bundle),
                "--certificate-identity",
                args.certificate_identity,
                "--certificate-oidc-issuer",
                issuer,
                str(args.manifest),
            ],
            check=True,
        )
    digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    print(
        json.dumps(
            {"manifest": str(args.manifest), "sha256": digest, "signature": str(output)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

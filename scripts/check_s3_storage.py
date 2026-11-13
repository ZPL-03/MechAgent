"""对真实 S3 兼容对象存储执行最小写入、校验、读取、列举和清理验收。"""

from __future__ import annotations

import argparse
import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

from mechagent.evidence import atomic_json, verify_manifest, write_manifest
from mechagent.runtime.artifacts import S3ArtifactStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True, help="S3 bucket 名称。")
    parser.add_argument("--prefix", default="mechagent-probe", help="对象前缀。")
    parser.add_argument("--endpoint-url", help="S3 兼容服务端点；AWS S3 可省略。")
    parser.add_argument("--region", help="AWS 区域。")
    parser.add_argument(
        "--require-lifecycle-id",
        help="要求桶存在指定 ID 且状态为 Enabled 的生命周期规则。",
    )
    parser.add_argument(
        "--keep-object",
        action="store_true",
        help="保留探针对象；默认删除以避免留下临时对象。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="可选证据目录；写入 probe.json 和可校验的 manifest.json。",
    )
    args = parser.parse_args(argv)
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError('真实 S3 探针需要安装 "mechagent[s3]"。') from exc

    client_kwargs: dict[str, Any] = {}
    if args.endpoint_url:
        client_kwargs["endpoint_url"] = args.endpoint_url
    if args.region:
        client_kwargs["region_name"] = args.region
    try:
        client = boto3.client("s3", **client_kwargs)
        store = S3ArtifactStore(args.bucket, args.prefix, client=client)
    except Exception as exc:  # boto3/provider errors must return a stable CLI failure
        result = {
            "status": "failed",
            "bucket": args.bucket,
            "prefix": args.prefix.strip("/"),
            "checks": {},
            "errors": [f"无法创建 S3 客户端：{_safe_error(exc)}"],
            "keep_object": args.keep_object,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    result = run_probe(
        client,
        store,
        require_lifecycle_id=args.require_lifecycle_id,
        keep_object=args.keep_object,
    )
    if args.output_dir:
        manifest = write_probe_evidence(result, args.output_dir)
        result["manifest"] = str(manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


def run_probe(
    client: Any,
    store: S3ArtifactStore,
    *,
    require_lifecycle_id: str | None,
    keep_object: bool,
) -> dict[str, Any]:
    """执行探针并返回不含凭据的结果；客户端由调用方注入以便隔离测试。"""

    content = secrets.token_bytes(128)
    try:
        digest = store.put_bytes(content)
    except Exception as exc:  # boto3/provider errors must remain an explicit failed result
        return {
            "status": "failed",
            "bucket": store.bucket,
            "prefix": store.prefix,
            "object_key": None,
            "checks": {"put": False},
            "errors": [f"对象写入失败：{_safe_error(exc)}"],
            "keep_object": keep_object,
        }
    key = store._key(digest)
    checks: dict[str, bool] = {"put": True}
    errors: list[str] = []
    try:
        checks["head_sha256"] = store.verify(digest)
        with tempfile.TemporaryDirectory(prefix="mechagent-s3-probe-") as temporary:
            destination = Path(temporary) / "roundtrip.bin"
            store.get_file(digest, destination)
            checks["get_sha256"] = destination.read_bytes() == content
        page = client.list_objects_v2(
            Bucket=store.bucket,
            Prefix=f"{store.prefix}/objects/" if store.prefix else "objects/",
        )
        keys = {str(item.get("Key", "")) for item in page.get("Contents", []) or []}
        checks["list"] = key in keys
        if not checks["head_sha256"]:
            errors.append("对象 metadata 中的 sha256 与内容摘要不一致。")
        if not checks["get_sha256"]:
            errors.append("对象下载后的内容摘要不一致。")
        if not checks["list"]:
            errors.append("对象列表未包含刚写入的对象。")
        _check_lifecycle(client, store.bucket, require_lifecycle_id, checks, errors)
    except Exception as exc:  # boto3 异常包含 provider-specific response
        errors.append(f"对象读回或列表检查失败：{_safe_error(exc)}")
        checks.setdefault("head_sha256", False)
        checks.setdefault("get_sha256", False)
        checks.setdefault("list", False)
    finally:
        if not keep_object:
            try:
                client.delete_object(Bucket=store.bucket, Key=key)
                checks["delete"] = True
            except Exception as exc:  # boto3 异常包含 provider-specific response
                checks["delete"] = False
                errors.append(
                    "探针对象删除失败；请执行："
                    f"aws s3api delete-object --bucket {store.bucket} --key {key}"
                    f"（错误类型：{_safe_error(exc)}）"
                )
    return {
        "status": "passed" if not errors and all(checks.values()) else "failed",
        "bucket": store.bucket,
        "prefix": store.prefix,
        "object_key": key,
        "checks": checks,
        "errors": errors,
        "keep_object": keep_object,
    }


def write_probe_evidence(result: dict[str, Any], output_dir: Path) -> Path:
    """把探针结果写入标准证据目录并校验目录完整性。"""

    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"S3 探针证据目录必须为空：{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / "probe.json", result)
    manifest = write_manifest(output_dir, status=str(result["status"]), details=result)
    errors = verify_manifest(manifest)
    if errors:
        raise RuntimeError("S3 探针证据清单校验失败：" + "; ".join(errors))
    return manifest


def _safe_error(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict) and error.get("Code"):
            return f"{type(exc).__name__}({error['Code']})"
    return type(exc).__name__


def _check_lifecycle(
    client: Any,
    bucket: str,
    required_id: str | None,
    checks: dict[str, bool],
    errors: list[str],
) -> None:
    if not required_id:
        checks["lifecycle_policy"] = True
        return
    try:
        response = client.get_bucket_lifecycle_configuration(Bucket=bucket)
    except Exception as exc:  # boto3 provider-specific missing-policy error
        checks["lifecycle_policy"] = False
        errors.append(f"无法读取桶生命周期配置：{_safe_error(exc)}")
        return
    rules = response.get("Rules", []) if isinstance(response, dict) else []
    matched = any(
        isinstance(rule, dict)
        and str(rule.get("ID", "")) == required_id
        and str(rule.get("Status", "")) == "Enabled"
        for rule in rules
    )
    checks["lifecycle_policy"] = matched
    if not matched:
        errors.append(f"桶缺少已启用的生命周期规则：{required_id}")


if __name__ == "__main__":
    raise SystemExit(main())

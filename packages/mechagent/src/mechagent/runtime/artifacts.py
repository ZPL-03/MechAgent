"""本地内容寻址对象存储和完整性校验。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any


class ArtifactStore:
    """以 SHA-256 为对象身份的不可变本地存储。

    对象路径只由摘要生成，输入路径不会参与目标路径拼接，因此不会把
    作业产物写出存储根目录。重复对象只保留一份内容。
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def put_file(self, source: Path) -> str:
        if not source.is_file():
            raise FileNotFoundError(source)
        digest = _sha256_file(source)
        destination = self.path_for(digest)
        if not destination.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + f".{os.getpid()}.tmp")
            source_bytes = source.read_bytes()
            temporary.write_bytes(source_bytes)
            if _sha256_file(temporary) != digest:
                temporary.unlink(missing_ok=True)
                raise ValueError("对象写入后完整性校验失败。")
            try:
                temporary.replace(destination)
            except FileExistsError:
                temporary.unlink(missing_ok=True)
        return digest

    def put_bytes(self, content: bytes) -> str:
        temporary = self.root / f".upload.{os.getpid()}.tmp"
        temporary.write_bytes(content)
        try:
            return self.put_file(temporary)
        finally:
            temporary.unlink(missing_ok=True)

    def path_for(self, digest: str) -> Path:
        _validate_digest(digest)
        return self.objects / digest[:2] / digest[2:]

    def get_file(self, digest: str, destination: Path) -> Path:
        source = self.path_for(digest)
        if not source.is_file() or _sha256_file(source) != digest:
            raise ValueError("对象缺失或完整性校验失败。")
        destination = destination.resolve()
        if destination == source:
            # 对象存储是不可变的；目标已经是对象本身时不能执行移动。
            return source
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        if _sha256_file(destination) != digest:
            raise ValueError("对象恢复后完整性校验失败。")
        return destination

    def verify(self, digest: str) -> bool:
        path = self.path_for(digest)
        return path.is_file() and _sha256_file(path) == digest


def _validate_digest(value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("对象摘要必须是 64 位小写 SHA-256。")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class S3ArtifactStore:
    """S3 兼容对象存储实现，保持与 ``ArtifactStore`` 相同的最小契约。

    生产部署通过 boto3 注入客户端或安装 ``mechagent[s3]``。对象键只由
    前缀和摘要组成；上传后以对象 metadata 中的 SHA-256 复核，恢复时再次
    对本地文件做摘要校验。凭据由 boto3 标准链提供，不从配置或日志读取。
    """

    def __init__(self, bucket: str, prefix: str = "mechagent/", *, client: Any = None) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket 不能为空。")
        self.bucket = bucket.strip()
        self.prefix = prefix.strip("/")
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("S3 对象存储需要安装 mechagent[s3]。") from exc
            client = boto3.client("s3")
        self.client = client

    def _key(self, digest: str) -> str:
        _validate_digest(digest)
        return (
            f"{self.prefix}/objects/{digest[:2]}/{digest[2:]}"
            if self.prefix
            else (f"objects/{digest[:2]}/{digest[2:]}")
        )

    def path_for(self, digest: str) -> str:
        return f"s3://{self.bucket}/{self._key(digest)}"

    def put_file(self, source: Path) -> str:
        if not source.is_file():
            raise FileNotFoundError(source)
        digest = _sha256_file(source)
        key = self._key(digest)
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
            if str(head.get("Metadata", {}).get("sha256", "")) == digest:
                return digest
        except Exception as exc:  # boto3 uses provider-specific not-found exceptions
            response = getattr(exc, "response", {}) or {}
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if code not in {
                "404",
                "NoSuchKey",
            }:
                raise
        self.client.upload_file(
            str(source),
            self.bucket,
            key,
            ExtraArgs={"Metadata": {"sha256": digest}},
        )
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        if str(head.get("Metadata", {}).get("sha256", "")) != digest:
            raise ValueError("S3 对象写入后完整性校验失败。")
        return digest

    def put_bytes(self, content: bytes) -> str:
        import io

        digest = hashlib.sha256(content).hexdigest()
        self.client.upload_fileobj(
            io.BytesIO(content),
            self.bucket,
            self._key(digest),
            ExtraArgs={"Metadata": {"sha256": digest}},
        )
        return digest

    def verify(self, digest: str) -> bool:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=self._key(digest))
        except Exception as exc:
            response = getattr(exc, "response", {}) or {}
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if code in {"404", "NoSuchKey"}:
                return False
            raise
        return str(head.get("Metadata", {}).get("sha256", "")) == digest

    def get_file(self, digest: str, destination: Path) -> Path:
        if not self.verify(digest):
            raise ValueError("S3 对象缺失或完整性校验失败。")
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, self._key(digest), str(destination))
        if _sha256_file(destination) != digest:
            destination.unlink(missing_ok=True)
            raise ValueError("S3 对象恢复后完整性校验失败。")
        return destination


def create_artifact_store(
    backend: str,
    *,
    root: Path | None = None,
    bucket: str = "",
    prefix: str = "mechagent",
) -> ArtifactStore | S3ArtifactStore:
    """按显式配置创建对象存储，不在后端不可用时静默降级。"""

    if backend == "filesystem":
        if root is None:
            raise ValueError("filesystem 对象存储需要 artifact_root。")
        return ArtifactStore(root)
    if backend == "s3":
        return S3ArtifactStore(bucket, prefix)
    raise ValueError(f"不支持的对象存储后端：{backend}")

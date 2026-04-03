"""S3 兼容对象存储实现（DogeCloud / MinIO / R2 等）。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from app.shared.infra.storage.base import ArtifactStore

if TYPE_CHECKING:
    from app.shared.infra.config import Settings

logger = structlog.get_logger()


class S3ArtifactStore(ArtifactStore):
    """基于 S3 兼容协议的 ArtifactStore 实现。"""

    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config as BotoConfig

        self._bucket = settings.s3_bucket or ""
        self._public_base_url = (settings.s3_public_base_url or "").rstrip("/")

        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region or "us-east-1",
            config=BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        logger.info(
            "s3_artifact_store_initialized",
            bucket=self._bucket,
            endpoint=settings.s3_endpoint,
        )

    def _run_sync(self, fn, *args, **kwargs):
        """将同步 boto3 调用包装为 async。"""
        return asyncio.to_thread(fn, *args, **kwargs)

    async def read_bytes(self, storage_key: str) -> bytes:
        resp = await self._run_sync(
            self._client.get_object,
            Bucket=self._bucket,
            Key=storage_key,
        )
        return resp["Body"].read()

    async def write_bytes(self, storage_key: str, data: bytes) -> None:
        await self._run_sync(
            self._client.put_object,
            Bucket=self._bucket,
            Key=storage_key,
            Body=data,
        )

    async def write_file(self, storage_key: str, local_path: Path) -> None:
        await self._run_sync(
            self._client.upload_file,
            str(local_path),
            self._bucket,
            storage_key,
        )

    async def delete(self, storage_key: str) -> None:
        await self._run_sync(
            self._client.delete_object,
            Bucket=self._bucket,
            Key=storage_key,
        )

    async def exists(self, storage_key: str) -> bool:
        try:
            await self._run_sync(
                self._client.head_object,
                Bucket=self._bucket,
                Key=storage_key,
            )
            return True
        except self._client.exceptions.NoSuchKey:
            return False
        except Exception:
            # head_object 在 key 不存在时可能抛 ClientError(404)
            return False

    async def list_prefix(self, prefix: str) -> list[str]:
        keys: list[str] = []
        continuation_token = None

        while True:
            kwargs: dict = {
                "Bucket": self._bucket,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token

            resp = await self._run_sync(self._client.list_objects_v2, **kwargs)

            for obj in resp.get("Contents", []):
                keys.append(obj["Key"])

            if not resp.get("IsTruncated"):
                break
            continuation_token = resp.get("NextContinuationToken")

        return keys

    async def delete_prefix(self, prefix: str) -> int:
        keys = await self.list_prefix(prefix)
        if not keys:
            return 0

        # S3 批量删除每次最多 1000 个
        deleted = 0
        for i in range(0, len(keys), 1000):
            batch = keys[i : i + 1000]
            await self._run_sync(
                self._client.delete_objects,
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
            )
            deleted += len(batch)

        return deleted

    async def materialize_to_temp(self, storage_key: str, temp_dir: Path) -> Path:
        temp_dir.mkdir(parents=True, exist_ok=True)
        # 保留原始文件名
        filename = storage_key.rsplit("/", 1)[-1] if "/" in storage_key else storage_key
        local_path = temp_dir / filename
        await self._run_sync(
            self._client.download_file,
            self._bucket,
            storage_key,
            str(local_path),
        )
        return local_path

    def public_url(self, storage_key: str) -> str | None:
        if not self._public_base_url:
            return None
        return f"{self._public_base_url}/{storage_key}"

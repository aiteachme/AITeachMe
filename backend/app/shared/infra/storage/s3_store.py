"""S3 兼容对象存储实现（DogeCloud / MinIO / R2 等）。"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3
import structlog
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from pydantic import AliasChoices, BaseModel, Field

from app.shared.infra.storage.base import ArtifactStore

if TYPE_CHECKING:
    from app.shared.infra.config import Settings

logger = structlog.get_logger()

_DOGECLOUD_REFRESH_SKEW = timedelta(minutes=5)
_DOGECLOUD_DEFAULT_TTL = timedelta(minutes=90)
_DOGECLOUD_TIMEOUT_SECONDS = 15
_AUTH_ERROR_CODES = {
    "ExpiredToken",
    "InvalidAccessKeyId",
    "RequestExpired",
    "SignatureDoesNotMatch",
}


class _ResolvedS3Credentials(BaseModel):
    bucket: str
    endpoint: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    session_token: str | None = None
    expires_at: datetime | None = None


class _DogeCloudCredentials(BaseModel):
    access_key_id: str = Field(validation_alias=AliasChoices("accessKeyId", "AccessKeyId"))
    secret_access_key: str = Field(validation_alias=AliasChoices("secretAccessKey", "SecretAccessKey"))
    session_token: str = Field(validation_alias=AliasChoices("sessionToken", "SessionToken"))
    expires_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("expiration", "Expiration", "expiredAt", "ExpiredAt"),
    )


class _DogeCloudBucketInfo(BaseModel):
    s3_bucket: str = Field(validation_alias=AliasChoices("s3Bucket", "S3Bucket"))
    s3_endpoint: str = Field(validation_alias=AliasChoices("s3Endpoint", "S3Endpoint"))


class _DogeCloudTmpTokenData(BaseModel):
    credentials: _DogeCloudCredentials = Field(validation_alias=AliasChoices("Credentials", "credentials"))
    buckets: list[_DogeCloudBucketInfo] = Field(validation_alias=AliasChoices("Buckets", "buckets"))


class _DogeCloudTmpTokenResponse(BaseModel):
    code: int
    msg: str | None = None
    data: _DogeCloudTmpTokenData | None = None


class S3ArtifactStore(ArtifactStore):
    """基于 S3 兼容协议的 ArtifactStore 实现。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._public_base_url = (settings.s3_public_base_url or "").rstrip("/")
        self._client_lock = Lock()
        self._client: Any | None = None
        self._bucket = settings.s3_bucket or ""
        self._endpoint = settings.s3_endpoint
        self._credentials_expire_at: datetime | None = None
        self._boto_config = BotoConfig(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            s3={"addressing_style": settings.resolved_s3_addressing_style},
        )

        self._refresh_client(force=True)
        logger.info(
            "s3_artifact_store_initialized",
            bucket=self._bucket,
            endpoint=self._endpoint,
            addressing_style=settings.resolved_s3_addressing_style,
            credential_mode=settings.resolved_s3_credential_mode,
            has_session_token=bool(self._settings.s3_session_token or self._settings.s3_uses_dogecloud_tmp_token),
        )

    def _run_sync(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """将同步 boto3 调用包装为 async。"""

        return asyncio.to_thread(fn, *args, **kwargs)

    def _credentials_need_refresh(self) -> bool:
        if self._client is None:
            return True
        if not self._settings.s3_uses_dogecloud_tmp_token:
            return False
        if self._credentials_expire_at is None:
            return False
        now = datetime.now(timezone.utc)
        return now + _DOGECLOUD_REFRESH_SKEW >= self._credentials_expire_at

    def _refresh_client(self, *, force: bool = False) -> Any:
        with self._client_lock:
            if not force and not self._credentials_need_refresh():
                return self._client

            credentials = self._resolve_credentials()
            self._bucket = credentials.bucket
            self._endpoint = credentials.endpoint or self._settings.s3_endpoint
            self._credentials_expire_at = credentials.expires_at
            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint,
                aws_access_key_id=credentials.access_key_id,
                aws_secret_access_key=credentials.secret_access_key,
                aws_session_token=credentials.session_token,
                region_name=self._settings.s3_region or "us-east-1",
                config=self._boto_config,
            )
            return self._client

    def _resolve_credentials(self) -> _ResolvedS3Credentials:
        if self._settings.s3_uses_dogecloud_tmp_token:
            return self._fetch_dogecloud_tmp_credentials()
        return _ResolvedS3Credentials(
            bucket=self._settings.s3_bucket or "",
            endpoint=self._settings.s3_endpoint,
            access_key_id=self._settings.s3_access_key,
            secret_access_key=self._settings.s3_secret_key,
            session_token=self._settings.s3_session_token,
        )

    def _fetch_dogecloud_tmp_credentials(self) -> _ResolvedS3Credentials:
        api_access_key = self._settings.resolved_dogecloud_api_access_key
        api_secret_key = self._settings.resolved_dogecloud_api_secret_key
        bucket = (self._settings.resolved_dogecloud_space_name or "").strip()
        if not api_access_key or not api_secret_key:
            raise ValueError("DogeCloud tmp_token 模式缺少 API AccessKey / SecretKey。")
        if not bucket:
            raise ValueError("DogeCloud tmp_token 模式缺少 DOGECLOUD_SPACE_NAME（或 S3_BUCKET）。")

        api_path = self._settings.dogecloud_tmp_token_path.strip() or "/auth/tmp_token.json"
        body = self._build_dogecloud_tmp_token_body(bucket)
        body_json = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        signature = hmac.new(
            api_secret_key.encode("utf-8"),
            f"{api_path}\n{body_json}".encode("utf-8"),
            hashlib.sha1,
        ).hexdigest()
        api_base_url = (self._settings.dogecloud_api_base_url or "https://api.dogecloud.com").rstrip("/")
        request = Request(
            url=f"{api_base_url}{api_path}",
            data=body_json.encode("utf-8"),
            headers={
                "Authorization": f"TOKEN {api_access_key}:{signature}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=_DOGECLOUD_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"DogeCloud tmp_token 请求失败: HTTP {exc.code} {details}".strip()) from exc
        except URLError as exc:
            raise RuntimeError(f"DogeCloud tmp_token 网络请求失败: {exc.reason}") from exc

        parsed = _DogeCloudTmpTokenResponse.model_validate(payload)
        if parsed.code != 200 or parsed.data is None or not parsed.data.buckets:
            raise RuntimeError(f"DogeCloud tmp_token 接口返回异常: code={parsed.code}, msg={parsed.msg or 'unknown'}")

        bucket_info = parsed.data.buckets[0]
        expires_at = parsed.data.credentials.expires_at
        if expires_at is None:
            expires_at = datetime.now(timezone.utc) + _DOGECLOUD_DEFAULT_TTL

        logger.info(
            "dogecloud_tmp_token_fetched",
            space_name=bucket,
            bucket=bucket_info.s3_bucket,
            endpoint=bucket_info.s3_endpoint,
            channel=(self._settings.dogecloud_tmp_token_channel or "").strip() or "OSS_FULL",
        )
        return _ResolvedS3Credentials(
            bucket=bucket_info.s3_bucket,
            endpoint=bucket_info.s3_endpoint,
            access_key_id=parsed.data.credentials.access_key_id,
            secret_access_key=parsed.data.credentials.secret_access_key,
            session_token=parsed.data.credentials.session_token,
            expires_at=expires_at,
        )

    def _build_dogecloud_tmp_token_body(self, bucket: str) -> dict[str, object]:
        channel = (self._settings.dogecloud_tmp_token_channel or "").strip() or "OSS_FULL"
        scope = (self._settings.dogecloud_tmp_token_scope or "").strip() or "*"
        return {
            "channel": channel,
            "scopes": [f"{bucket}:{scope}"],
        }

    def _call_with_refresh(self, client_call: Callable[[Any], Any]) -> Any:
        client = self._refresh_client()
        try:
            return client_call(client)
        except ClientError as exc:
            if not self._settings.s3_uses_dogecloud_tmp_token:
                raise
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code not in _AUTH_ERROR_CODES:
                raise

        logger.warning("s3_client_retry_with_refreshed_credentials", bucket=self._bucket, endpoint=self._endpoint)
        client = self._refresh_client(force=True)
        return client_call(client)

    async def read_bytes(self, storage_key: str) -> bytes:
        resp = await self._run_sync(
            self._call_with_refresh,
            lambda client: client.get_object(Bucket=self._bucket, Key=storage_key),
        )
        return resp["Body"].read()

    async def write_bytes(self, storage_key: str, data: bytes) -> None:
        await self._run_sync(
            self._call_with_refresh,
            lambda client: client.put_object(Bucket=self._bucket, Key=storage_key, Body=data),
        )

    async def write_file(self, storage_key: str, local_path: Path) -> None:
        await self._run_sync(
            self._call_with_refresh,
            lambda client: client.upload_file(str(local_path), self._bucket, storage_key),
        )

    async def delete(self, storage_key: str) -> None:
        await self._run_sync(
            self._call_with_refresh,
            lambda client: client.delete_object(Bucket=self._bucket, Key=storage_key),
        )

    async def exists(self, storage_key: str) -> bool:
        try:
            await self._run_sync(
                self._call_with_refresh,
                lambda client: client.head_object(Bucket=self._bucket, Key=storage_key),
            )
            return True
        except self._client.exceptions.NoSuchKey:
            return False
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return False
            return False
        except Exception:
            return False

    async def list_prefix(self, prefix: str) -> list[str]:
        keys: list[str] = []
        continuation_token = None

        while True:
            kwargs: dict[str, object] = {
                "Bucket": self._bucket,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token

            resp = await self._run_sync(
                self._call_with_refresh,
                lambda client: client.list_objects_v2(**kwargs),
            )

            keys.extend(obj["Key"] for obj in resp.get("Contents", []))

            if not resp.get("IsTruncated"):
                break
            continuation_token = resp.get("NextContinuationToken")

        return keys

    async def delete_prefix(self, prefix: str) -> int:
        keys = await self.list_prefix(prefix)
        if not keys:
            return 0

        deleted = 0
        for index in range(0, len(keys), 1000):
            batch = keys[index : index + 1000]
            await self._run_sync(
                self._call_with_refresh,
                lambda client: client.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
                ),
            )
            deleted += len(batch)

        return deleted

    async def materialize_to_temp(self, storage_key: str, temp_dir: Path) -> Path:
        temp_dir.mkdir(parents=True, exist_ok=True)
        filename = storage_key.rsplit("/", 1)[-1] if "/" in storage_key else storage_key
        local_path = temp_dir / filename
        await self._run_sync(
            self._call_with_refresh,
            lambda client: client.download_file(self._bucket, storage_key, str(local_path)),
        )
        return local_path

    def public_url(self, storage_key: str) -> str | None:
        if not self._public_base_url:
            return None
        return f"{self._public_base_url}/{storage_key}"

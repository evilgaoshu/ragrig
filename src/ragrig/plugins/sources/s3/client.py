from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ragrig.plugins.sources.s3.errors import (
    S3ConfigError,
    S3CredentialError,
    S3PermanentError,
    S3RetryableError,
)


@dataclass(frozen=True)
class S3ObjectMetadata:
    key: str
    etag: str
    last_modified: datetime
    size: int
    content_type: str | None


@dataclass(frozen=True)
class S3ListResult:
    objects: list[S3ObjectMetadata]
    next_token: str | None = None


@dataclass(frozen=True)
class FakeS3Object:
    key: str
    body: bytes
    etag: str
    last_modified: datetime
    content_type: str | None = None


class S3ClientProtocol(Protocol):
    def list_objects(
        self,
        *,
        bucket: str,
        prefix: str,
        continuation_token: str | None,
        max_keys: int,
    ) -> S3ListResult: ...

    def download_object(self, *, bucket: str, key: str) -> bytes: ...


@dataclass
class FakeS3Client:
    objects: list[FakeS3Object] = field(default_factory=list)
    list_error: Exception | None = None
    download_failures: dict[str, list[Exception]] = field(default_factory=dict)

    def list_objects(
        self,
        *,
        bucket: str,
        prefix: str,
        continuation_token: str | None,
        max_keys: int,
    ) -> S3ListResult:
        del bucket
        if self.list_error is not None:
            raise self.list_error

        filtered = sorted(
            (item for item in self.objects if item.key.startswith(prefix)),
            key=lambda item: item.key,
        )
        start = int(continuation_token or 0)
        page = filtered[start : start + max_keys]
        next_token = None
        if start + max_keys < len(filtered):
            next_token = str(start + max_keys)
        return S3ListResult(
            objects=[
                S3ObjectMetadata(
                    key=item.key,
                    etag=item.etag,
                    last_modified=item.last_modified,
                    size=len(item.body),
                    content_type=item.content_type,
                )
                for item in page
            ],
            next_token=next_token,
        )

    def download_object(self, *, bucket: str, key: str) -> bytes:
        del bucket
        failures = self.download_failures.get(key, [])
        if failures:
            error = failures.pop(0)
            raise error
        for item in self.objects:
            if item.key == key:
                return item.body
        raise S3PermanentError(f"object not found: {key}")


def build_boto3_client(config: dict[str, object]) -> S3ClientProtocol:
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except ImportError as exc:  # pragma: no cover - exercised by contract/discovery tests
        raise S3ConfigError("boto3 is required for source.s3") from exc

    class _Boto3S3Client:
        def __init__(self) -> None:
            session = boto3.session.Session(
                aws_access_key_id=config["access_key"],
                aws_secret_access_key=config["secret_key"],
                aws_session_token=config.get("session_token"),
                region_name=config.get("region"),
            )
            self._client = session.client(
                "s3",
                endpoint_url=config.get("endpoint_url"),
                verify=config.get("verify_tls", True),
                config=Config(
                    s3={"addressing_style": "path" if config.get("use_path_style") else "auto"},
                    retries={"max_attempts": config.get("max_retries", 3) + 1, "mode": "standard"},
                    connect_timeout=config.get("connect_timeout_seconds", 10),
                    read_timeout=config.get("read_timeout_seconds", 30),
                ),
            )

        def list_objects(
            self,
            *,
            bucket: str,
            prefix: str,
            continuation_token: str | None,
            max_keys: int,
        ) -> S3ListResult:
            try:
                params: dict[str, object] = {
                    "Bucket": bucket,
                    "Prefix": prefix,
                    "MaxKeys": max_keys,
                }
                if continuation_token is not None:
                    params["ContinuationToken"] = continuation_token
                response = self._client.list_objects_v2(**params)
            except NoCredentialsError as exc:
                raise S3CredentialError("credentials are not configured for source.s3") from exc
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied"}:
                    raise S3CredentialError("credentials were rejected for source.s3") from exc
                raise S3PermanentError("list_objects_v2 failed") from exc
            except BotoCoreError as exc:
                raise S3RetryableError("list_objects_v2 failed") from exc

            objects = [
                S3ObjectMetadata(
                    key=item["Key"],
                    etag=str(item.get("ETag", "")).strip('"'),
                    last_modified=item["LastModified"],
                    size=item["Size"],
                    content_type=item.get("ContentType"),
                )
                for item in response.get("Contents", [])
            ]
            next_token = response.get("NextContinuationToken")
            return S3ListResult(objects=objects, next_token=next_token)

        def download_object(self, *, bucket: str, key: str) -> bytes:
            try:
                response = self._client.get_object(Bucket=bucket, Key=key)
                return response["Body"].read()
            except NoCredentialsError as exc:
                raise S3CredentialError("credentials are not configured for source.s3") from exc
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied"}:
                    raise S3CredentialError("credentials were rejected for source.s3") from exc
                if code in {"RequestTimeout", "SlowDown", "InternalError", "ServiceUnavailable"}:
                    raise S3RetryableError(f"temporary object read failure for {key}") from exc
                raise S3PermanentError(f"permanent object read failure for {key}") from exc
            except BotoCoreError as exc:
                raise S3RetryableError(f"temporary object read failure for {key}") from exc

    return _Boto3S3Client()

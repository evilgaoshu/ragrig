from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from ragrig.plugins.object_storage.errors import (
    ObjectStorageConfigError,
    ObjectStorageCredentialError,
    ObjectStoragePermanentError,
    ObjectStorageRetryableError,
)


@dataclass(frozen=True)
class FakeStoredObject:
    key: str
    body: bytes
    content_type: str
    metadata: dict[str, str]
    last_modified: datetime


class ObjectStorageClientProtocol(Protocol):
    def check_bucket_access(self, *, bucket: str, prefix: str) -> None: ...

    def get_object(self, *, bucket: str, key: str) -> FakeStoredObject | None: ...

    def put_object(
        self,
        *,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None: ...


@dataclass
class FakeObjectStorageClient:
    objects: dict[str, FakeStoredObject] = field(default_factory=dict)
    list_error: Exception | None = None
    put_failures: dict[str, list[Exception]] = field(default_factory=dict)
    put_attempts: dict[str, int] = field(default_factory=dict)

    def check_bucket_access(self, *, bucket: str, prefix: str) -> None:
        del bucket, prefix
        if self.list_error is not None:
            raise self.list_error

    def get_object(self, *, bucket: str, key: str) -> FakeStoredObject | None:
        del bucket
        return self.objects.get(key)

    def put_object(
        self,
        *,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        del bucket
        self.put_attempts[key] = self.put_attempts.get(key, 0) + 1
        failures = self.put_failures.get(key, [])
        if failures:
            error = failures.pop(0)
            raise error
        self.objects[key] = FakeStoredObject(
            key=key,
            body=body,
            content_type=content_type,
            metadata=dict(metadata),
            last_modified=datetime.now(timezone.utc),
        )


def build_boto3_object_storage_client(config: dict[str, object]) -> ObjectStorageClientProtocol:
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except ImportError as exc:  # pragma: no cover
        raise ObjectStorageConfigError("boto3 is required for sink.object_storage") from exc

    class _Boto3ObjectStorageClient:
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

        def check_bucket_access(self, *, bucket: str, prefix: str) -> None:
            try:
                self._client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
            except NoCredentialsError as exc:
                raise ObjectStorageCredentialError(
                    "credentials are not configured for sink.object_storage"
                ) from exc
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied"}:
                    raise ObjectStorageCredentialError(
                        "credentials were rejected for sink.object_storage"
                    ) from exc
                if code in {"RequestTimeout", "SlowDown", "InternalError", "ServiceUnavailable"}:
                    raise ObjectStorageRetryableError("bucket access check failed") from exc
                raise ObjectStoragePermanentError("bucket access denied") from exc
            except BotoCoreError as exc:
                raise ObjectStorageRetryableError("bucket access check failed") from exc

        def get_object(self, *, bucket: str, key: str) -> FakeStoredObject | None:
            try:
                response = self._client.head_object(Bucket=bucket, Key=key)
            except NoCredentialsError as exc:
                raise ObjectStorageCredentialError(
                    "credentials are not configured for sink.object_storage"
                ) from exc
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"404", "NoSuchKey", "NotFound"}:
                    return None
                if code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied"}:
                    raise ObjectStorageCredentialError(
                        "credentials were rejected for sink.object_storage"
                    ) from exc
                if code in {"RequestTimeout", "SlowDown", "InternalError", "ServiceUnavailable"}:
                    raise ObjectStorageRetryableError(f"head_object failed for {key}") from exc
                raise ObjectStoragePermanentError(f"head_object failed for {key}") from exc
            except BotoCoreError as exc:
                raise ObjectStorageRetryableError(f"head_object failed for {key}") from exc

            metadata = {
                str(name): str(value) for name, value in response.get("Metadata", {}).items()
            }
            return FakeStoredObject(
                key=key,
                body=b"",
                content_type=response.get("ContentType", "application/octet-stream"),
                metadata=metadata,
                last_modified=response.get("LastModified", datetime.now(timezone.utc)),
            )

        def put_object(
            self,
            *,
            bucket: str,
            key: str,
            body: bytes,
            content_type: str,
            metadata: dict[str, str],
        ) -> None:
            try:
                self._client.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=body,
                    ContentType=content_type,
                    Metadata=metadata,
                )
            except NoCredentialsError as exc:
                raise ObjectStorageCredentialError(
                    "credentials are not configured for sink.object_storage"
                ) from exc
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied"}:
                    raise ObjectStorageCredentialError(
                        "credentials were rejected for sink.object_storage"
                    ) from exc
                if code in {"RequestTimeout", "SlowDown", "InternalError", "ServiceUnavailable"}:
                    raise ObjectStorageRetryableError(f"put_object failed for {key}") from exc
                raise ObjectStoragePermanentError(f"put_object failed for {key}") from exc
            except BotoCoreError as exc:
                raise ObjectStorageRetryableError(f"put_object failed for {key}") from exc

    return _Boto3ObjectStorageClient()

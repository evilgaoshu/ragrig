from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

from ragrig.plugins.sources.s3.config import ResolvedS3Credentials, S3SourceConfig
from ragrig.plugins.sources.s3.errors import (
    MissingDependencyError,
    PermanentObjectError,
    RetryableObjectError,
    S3ConfigError,
    S3CredentialError,
)


@dataclass(frozen=True)
class S3ObjectMetadata:
    key: str
    etag: str
    last_modified: datetime
    size: int
    content_type: str | None = None


@dataclass(frozen=True)
class ListObjectsPage:
    objects: list[S3ObjectMetadata]
    continuation_token: str | None = None


class S3ClientProtocol(Protocol):
    def list_objects(
        self,
        *,
        bucket: str,
        prefix: str,
        continuation_token: str | None,
        page_size: int,
    ) -> ListObjectsPage: ...

    def download_object(self, *, bucket: str, key: str, destination: Path) -> None: ...


@dataclass
class FakeS3Object:
    key: str
    body: bytes
    etag: str
    last_modified: datetime
    content_type: str | None = None
    download_errors: list[Exception] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.body)


class FakeS3Client(S3ClientProtocol):
    def __init__(
        self,
        objects: list[FakeS3Object],
        *,
        list_error: Exception | None = None,
    ) -> None:
        self._objects = {item.key: item for item in objects}
        self._list_error = list_error

    def list_objects(
        self,
        *,
        bucket: str,
        prefix: str,
        continuation_token: str | None,
        page_size: int,
    ) -> ListObjectsPage:
        del bucket
        if self._list_error is not None:
            raise self._list_error
        keys = sorted(key for key in self._objects if key.startswith(prefix))
        start = int(continuation_token or "0")
        end = start + page_size
        objects = [self._to_metadata(self._objects[key]) for key in keys[start:end]]
        next_token = str(end) if end < len(keys) else None
        return ListObjectsPage(objects=objects, continuation_token=next_token)

    def download_object(self, *, bucket: str, key: str, destination: Path) -> None:
        del bucket
        item = self._objects[key]
        if item.download_errors:
            raise item.download_errors.pop(0)
        destination.write_bytes(item.body)

    @staticmethod
    def _to_metadata(item: FakeS3Object) -> S3ObjectMetadata:
        return S3ObjectMetadata(
            key=item.key,
            etag=item.etag,
            last_modified=item.last_modified,
            size=item.size,
            content_type=item.content_type,
        )


class Boto3S3Client(S3ClientProtocol):
    def __init__(self, *, config: S3SourceConfig, credentials: ResolvedS3Credentials) -> None:
        sdk = _load_sdk_modules()
        self._exceptions = sdk.exceptions
        session = sdk.boto3.session.Session()
        self._client = session.client(
            "s3",
            aws_access_key_id=credentials.access_key,
            aws_secret_access_key=credentials.secret_key,
            aws_session_token=credentials.session_token,
            endpoint_url=config.endpoint_url,
            region_name=config.region,
            verify=config.verify_tls,
            config=sdk.config.Config(
                connect_timeout=config.connect_timeout_seconds,
                read_timeout=config.read_timeout_seconds,
                retries={"max_attempts": max(config.max_retries, 1), "mode": "standard"},
                s3={"addressing_style": "path" if config.use_path_style else "auto"},
            ),
        )

    def list_objects(
        self,
        *,
        bucket: str,
        prefix: str,
        continuation_token: str | None,
        page_size: int,
    ) -> ListObjectsPage:
        try:
            response = self._client.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                ContinuationToken=continuation_token,
                MaxKeys=page_size,
            )
        except self._exceptions.NoCredentialsError as exc:
            raise S3CredentialError("S3 credentials are invalid or missing") from exc
        except self._exceptions.PartialCredentialsError as exc:
            raise S3CredentialError("S3 credentials are incomplete") from exc
        except self._exceptions.ClientError as exc:
            raise _translate_client_error(exc, key=None) from exc

        objects = [
            S3ObjectMetadata(
                key=item["Key"],
                etag=str(item.get("ETag", "")).strip('"'),
                last_modified=item["LastModified"],
                size=int(item["Size"]),
                content_type=item.get("ContentType"),
            )
            for item in response.get("Contents", [])
        ]
        return ListObjectsPage(
            objects=objects,
            continuation_token=response.get("NextContinuationToken"),
        )

    def download_object(self, *, bucket: str, key: str, destination: Path) -> None:
        try:
            self._client.download_file(bucket, key, str(destination))
        except self._exceptions.NoCredentialsError as exc:
            raise S3CredentialError("S3 credentials are invalid or missing") from exc
        except self._exceptions.PartialCredentialsError as exc:
            raise S3CredentialError("S3 credentials are incomplete") from exc
        except self._exceptions.ClientError as exc:
            raise _translate_client_error(exc, key=key) from exc


def _load_sdk_modules() -> SimpleNamespace:
    try:
        boto3 = import_module("boto3")
        botocore_config = import_module("botocore.config")
        botocore_exceptions = import_module("botocore.exceptions")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "source.s3 requires the optional 'ragrig[s3]' dependency group"
        ) from exc
    return SimpleNamespace(
        boto3=boto3,
        config=botocore_config,
        exceptions=botocore_exceptions,
    )


def _translate_client_error(exc: Exception, *, key: str | None) -> Exception:
    response = getattr(exc, "response", {}) or {}
    error = response.get("Error", {})
    code = error.get("Code")
    if code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied"}:
        raise S3CredentialError("S3 credentials were rejected")
    if code in {"NoSuchBucket", "InvalidBucketName", "PermanentRedirect"}:
        raise S3ConfigError("S3 bucket or endpoint configuration is invalid")
    if code in {"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable"}:
        target = key or "bucket listing"
        raise RetryableObjectError(f"Transient S3 error while reading {target}")
    target = key or "bucket listing"
    raise PermanentObjectError(f"Failed to read {target}")

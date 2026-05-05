from ragrig.plugins.object_storage.client import (
    FakeObjectStorageClient,
    FakeStoredObject,
    ObjectStorageClientProtocol,
    build_boto3_object_storage_client,
)
from ragrig.plugins.object_storage.config import ObjectStorageSinkConfig
from ragrig.plugins.object_storage.errors import (
    ObjectStorageConfigError,
    ObjectStorageCredentialError,
    ObjectStoragePermanentError,
    ObjectStorageRetryableError,
    sanitize_error_message,
)

__all__ = [
    "FakeObjectStorageClient",
    "FakeStoredObject",
    "ObjectStorageClientProtocol",
    "ObjectStorageConfigError",
    "ObjectStorageCredentialError",
    "ObjectStoragePermanentError",
    "ObjectStorageRetryableError",
    "ObjectStorageSinkConfig",
    "build_boto3_object_storage_client",
    "sanitize_error_message",
]

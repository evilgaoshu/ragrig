from __future__ import annotations


class S3SourceError(Exception):
    """Base error for S3 source ingestion."""


class MissingDependencyError(S3SourceError):
    """Raised when the optional S3 SDK is unavailable."""


class S3ConfigError(S3SourceError):
    """Raised when the S3 source configuration is invalid."""


class S3CredentialError(S3SourceError):
    """Raised when the connector cannot authenticate to the remote bucket."""


class RetryableObjectError(S3SourceError):
    """Raised for transient per-object errors that should be retried."""


class PermanentObjectError(S3SourceError):
    """Raised for permanent per-object failures."""

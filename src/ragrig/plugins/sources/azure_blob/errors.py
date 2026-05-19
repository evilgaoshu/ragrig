from __future__ import annotations


class AzureBlobSourceError(RuntimeError):
    pass


class AzureBlobAuthError(AzureBlobSourceError):
    pass


class AzureBlobConfigError(AzureBlobSourceError):
    pass

from __future__ import annotations


class GcsSourceError(RuntimeError):
    pass


class GcsAuthError(GcsSourceError):
    pass


class GcsConfigError(GcsSourceError):
    pass

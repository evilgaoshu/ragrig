from __future__ import annotations


class CloudflareR2SourceError(Exception):
    pass


class CloudflareR2AuthError(CloudflareR2SourceError):
    pass


class CloudflareR2ConfigError(CloudflareR2SourceError):
    pass

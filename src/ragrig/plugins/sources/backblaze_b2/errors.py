from __future__ import annotations


class BackblazeB2SourceError(Exception):
    pass


class BackblazeB2AuthError(BackblazeB2SourceError):
    pass


class BackblazeB2ConfigError(BackblazeB2SourceError):
    pass

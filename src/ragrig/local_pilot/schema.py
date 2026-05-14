from __future__ import annotations

from pydantic import BaseModel


class LocalPilotUploadStatus(BaseModel):
    extensions: list[str]
    max_file_size_mb: int


class LocalPilotWebsiteStatus(BaseModel):
    max_pages: int
    modes: list[str]


class LocalPilotModelStatus(BaseModel):
    required: list[str]
    local_first: list[str]
    cloud_supported: list[str]


class LocalPilotStatus(BaseModel):
    upload: LocalPilotUploadStatus
    website_import: LocalPilotWebsiteStatus
    models: LocalPilotModelStatus


class LocalPilotAnswerSmokeRequest(BaseModel):
    provider: str
    model: str | None = None


class LocalPilotAnswerSmokeReport(BaseModel):
    provider: str
    model: str | None
    status: str
    detail: str

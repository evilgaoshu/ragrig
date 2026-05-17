"""飞书 / Lark connector.

Uses the Lark Open Platform's docx + wiki APIs to enumerate documents and
fetch their plain-text content.

The connector first exchanges ``app_id`` + ``app_secret`` for a
``tenant_access_token`` (cached for the call), then issues:

- ``POST /open-apis/wiki/v2/spaces/{space}/nodes``  — list pages in a space
- ``GET  /open-apis/docx/v1/documents/{doc}/raw_content`` — full text body

Configuration shape::

    {
        "base_url": "https://open.feishu.cn",
        "space_id": "wiki-space-id",
        "app_id": "env:FEISHU_APP_ID",
        "app_secret": "env:FEISHU_APP_SECRET",
        "page_size": 50,
    }
"""

from ragrig.plugins.sources.feishu.config import FeishuSourceConfig
from ragrig.plugins.sources.feishu.errors import (
    FeishuAuthError,
    FeishuConfigError,
    FeishuSourceError,
)
from ragrig.plugins.sources.feishu.scanner import (
    FeishuItem,
    FeishuScanResult,
    scan_feishu_documents,
)

__all__ = [
    "FeishuAuthError",
    "FeishuConfigError",
    "FeishuItem",
    "FeishuScanResult",
    "FeishuSourceConfig",
    "FeishuSourceError",
    "scan_feishu_documents",
]

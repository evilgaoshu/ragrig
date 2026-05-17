from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ragrig.plugins import get_plugin_registry


@dataclass(frozen=True)
class EnterpriseConnectorSpec:
    plugin_id: str
    display_name: str
    family: str
    protocols: tuple[str, ...]
    official_docs_url: str
    required_credentials: tuple[str, ...] = ()
    workflow_operation: str = "ingest.connector"
    supports_live_probe: bool = False
    notes: str | None = None


ENTERPRISE_CONNECTORS: dict[str, EnterpriseConnectorSpec] = {
    "source.local": EnterpriseConnectorSpec(
        plugin_id="source.local",
        display_name="Local Files",
        family="local",
        protocols=("filesystem",),
        official_docs_url="https://github.com/evilgaoshu/ragrig#quick-start",
        workflow_operation="ingest.local",
        supports_live_probe=True,
    ),
    "source.fileshare": EnterpriseConnectorSpec(
        plugin_id="source.fileshare",
        display_name="Enterprise Fileshare",
        family="fileshare",
        protocols=("nfs-mounted", "smb", "webdav", "sftp"),
        official_docs_url="https://learn.microsoft.com/en-us/windows-server/storage/file-server/file-server-smb-overview",
        required_credentials=("FILESHARE_USERNAME", "FILESHARE_PASSWORD"),
        workflow_operation="ingest.fileshare",
        supports_live_probe=True,
        notes=(
            "NFS mounted paths can be checked locally; remote protocols require configured secrets."
        ),
    ),
    "source.s3": EnterpriseConnectorSpec(
        plugin_id="source.s3",
        display_name="S3-Compatible Object Storage",
        family="object_storage",
        protocols=("s3-api",),
        official_docs_url="https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html",
        required_credentials=("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"),
        workflow_operation="ingest.s3",
    ),
    "source.google_workspace": EnterpriseConnectorSpec(
        plugin_id="source.google_workspace",
        display_name="Google Workspace",
        family="google_workspace",
        protocols=("google-drive-api",),
        official_docs_url="https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list",
        required_credentials=("GOOGLE_SERVICE_ACCOUNT_JSON",),
    ),
    "source.microsoft_365": EnterpriseConnectorSpec(
        plugin_id="source.microsoft_365",
        display_name="Microsoft 365",
        family="microsoft_365",
        protocols=("microsoft-graph", "sharepoint", "onedrive"),
        official_docs_url="https://learn.microsoft.com/en-us/graph/api/driveitem-list-children?view=graph-rest-1.0",
        required_credentials=("MICROSOFT_365_CLIENT_SECRET",),
    ),
    "source.wiki": EnterpriseConnectorSpec(
        plugin_id="source.wiki",
        display_name="Enterprise Wiki",
        family="wiki",
        protocols=("confluence-rest", "mediawiki-api"),
        official_docs_url="https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-search/",
        required_credentials=("WIKI_ACCESS_TOKEN",),
    ),
    "source.database": EnterpriseConnectorSpec(
        plugin_id="source.database",
        display_name="Database Source",
        family="database",
        protocols=("postgresql", "mysql"),
        official_docs_url="https://www.postgresql.org/docs/current/libpq-connect.html",
        required_credentials=("SOURCE_DATABASE_DSN",),
        workflow_operation="ingest.database",
        supports_live_probe=True,
        notes="Read-only SQL query ingestion; MySQL requires the pymysql optional dependency.",
    ),
    "source.collaboration": EnterpriseConnectorSpec(
        plugin_id="source.collaboration",
        display_name="Collaboration Suite",
        family="collaboration",
        protocols=("notion", "slack", "lark", "dingtalk", "wecom", "teams"),
        official_docs_url="https://developers.notion.com/reference/post-search",
        required_credentials=("COLLABORATION_ACCESS_TOKEN",),
    ),
    "source.notion": EnterpriseConnectorSpec(
        plugin_id="source.notion",
        display_name="Notion",
        family="collaboration",
        protocols=("notion-api",),
        official_docs_url="https://developers.notion.com/reference/post-search",
        required_credentials=("NOTION_API_KEY",),
    ),
    "source.confluence": EnterpriseConnectorSpec(
        plugin_id="source.confluence",
        display_name="Confluence Cloud",
        family="wiki",
        protocols=("confluence-rest",),
        official_docs_url="https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-content/",
        required_credentials=("CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN"),
        notes="Uses Basic Auth (email + API token); space_key narrows the scan to one space.",
    ),
    "source.feishu": EnterpriseConnectorSpec(
        plugin_id="source.feishu",
        display_name="Feishu / Lark Wiki",
        family="collaboration",
        protocols=("lark-open",),
        official_docs_url="https://open.feishu.cn/document/server-docs/docs/wiki-v2/space/list",
        required_credentials=("FEISHU_APP_ID", "FEISHU_APP_SECRET"),
        notes="Exchanges app credentials for tenant_access_token before listing wiki nodes.",
    ),
    "source.slack": EnterpriseConnectorSpec(
        plugin_id="source.slack",
        display_name="Slack Files",
        family="collaboration",
        protocols=("slack-web-api",),
        official_docs_url="https://docs.slack.dev/reference/methods/files.list/",
        required_credentials=("SLACK_BOT_TOKEN",),
    ),
    "source.box": EnterpriseConnectorSpec(
        plugin_id="source.box",
        display_name="Box",
        family="document_hub",
        protocols=("box-api",),
        official_docs_url="https://box.dev/reference/get-folders-id-items/",
        required_credentials=("BOX_ACCESS_TOKEN",),
    ),
    "source.dropbox": EnterpriseConnectorSpec(
        plugin_id="source.dropbox",
        display_name="Dropbox",
        family="document_hub",
        protocols=("dropbox-api",),
        official_docs_url="https://www.dropbox.com/developers/documentation/http/documentation#files-list_folder",
        required_credentials=("DROPBOX_ACCESS_TOKEN",),
    ),
    "source.github": EnterpriseConnectorSpec(
        plugin_id="source.github",
        display_name="GitHub Repository Contents",
        family="developer_knowledge",
        protocols=("github-rest",),
        official_docs_url="https://docs.github.com/en/rest/repos/contents?apiVersion=2022-11-28",
        required_credentials=("GITHUB_TOKEN",),
    ),
}


def list_enterprise_connectors() -> list[dict[str, object]]:
    registry = get_plugin_registry()
    plugin_discovery = {item["plugin_id"]: item for item in registry.list_discovery()}
    items: list[dict[str, object]] = []
    for spec in sorted(ENTERPRISE_CONNECTORS.values(), key=lambda item: item.plugin_id):
        plugin_item = plugin_discovery.get(spec.plugin_id, {})
        items.append(
            {
                "plugin_id": spec.plugin_id,
                "display_name": spec.display_name,
                "family": spec.family,
                "protocols": list(spec.protocols),
                "official_docs_url": spec.official_docs_url,
                "required_credentials": list(spec.required_credentials),
                "workflow_operation": spec.workflow_operation,
                "supports_live_probe": spec.supports_live_probe,
                "status": plugin_item.get("status", "planned"),
                "reason": plugin_item.get("reason") or plugin_item.get("unavailable_reason"),
                "capabilities": plugin_item.get("capabilities", ["read"]),
                "example_config": _safe_example_config(spec.plugin_id),
                "notes": spec.notes,
            }
        )
    return items


def probe_enterprise_connector(
    connector_id: str,
    *,
    config: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    spec = ENTERPRISE_CONNECTORS.get(connector_id)
    if spec is None:
        return {
            "connector_id": connector_id,
            "status": "unknown_connector",
            "network_called": False,
        }
    active_env = os.environ if env is None else env
    missing = [name for name in spec.required_credentials if not active_env.get(name)]
    if connector_id == "source.fileshare" and (config or {}).get("protocol") == "nfs_mounted":
        missing = []
    if missing:
        return {
            "connector_id": connector_id,
            "status": "missing_credentials",
            "missing_credentials": missing,
            "network_called": False,
            "official_docs_url": spec.official_docs_url,
        }
    if connector_id == "source.local":
        root_path = Path(str((config or {}).get("root_path") or ""))
        if not root_path.exists():
            return {
                "connector_id": connector_id,
                "status": "unavailable",
                "reason": "root_path_not_found",
                "network_called": False,
                "official_docs_url": spec.official_docs_url,
            }
        return {
            "connector_id": connector_id,
            "status": "ready",
            "network_called": False,
            "official_docs_url": spec.official_docs_url,
        }
    if connector_id == "source.fileshare" and (config or {}).get("protocol") == "nfs_mounted":
        root_path = Path(str((config or {}).get("root_path") or ""))
        return {
            "connector_id": connector_id,
            "status": "ready" if root_path.exists() else "unavailable",
            "reason": None if root_path.exists() else "root_path_not_found",
            "network_called": False,
            "official_docs_url": spec.official_docs_url,
        }
    if connector_id == "source.database":
        engine = str((config or {}).get("engine") or "postgresql")
        if engine not in {"postgresql", "mysql"}:
            return {
                "connector_id": connector_id,
                "status": "unavailable",
                "reason": "unsupported_database_engine",
                "network_called": False,
                "official_docs_url": spec.official_docs_url,
            }
        return {
            "connector_id": connector_id,
            "status": "contract_ready",
            "engine": engine,
            "network_called": False,
            "official_docs_url": spec.official_docs_url,
            "reason": "live database probes require explicit connector execution",
        }
    return {
        "connector_id": connector_id,
        "status": "contract_ready",
        "network_called": False,
        "official_docs_url": spec.official_docs_url,
        "reason": (
            "live network probes require explicit runtime credentials and connector execution"
        ),
    }


def _safe_example_config(plugin_id: str) -> dict[str, object]:
    if plugin_id == "source.local":
        return {"root_path": "/data/docs"}
    if plugin_id == "source.fileshare":
        return {"protocol": "nfs_mounted", "root_path": "/mnt/share/docs"}
    if plugin_id == "source.s3":
        return {"bucket": "knowledge", "prefix": "docs/"}
    if plugin_id == "source.google_workspace":
        return {"drive_id": "shared-drive-id"}
    if plugin_id == "source.microsoft_365":
        return {"tenant_id": "tenant-id", "client_id": "client-id"}
    if plugin_id == "source.wiki":
        return {"base_url": "https://wiki.example.com"}
    if plugin_id == "source.confluence":
        return {
            "base_url": "https://example.atlassian.net/wiki",
            "space_key": "ENG",
            "email": "env:CONFLUENCE_EMAIL",
            "api_token": "env:CONFLUENCE_API_TOKEN",
        }
    if plugin_id == "source.notion":
        return {
            "api_token": "env:NOTION_API_KEY",
            "filter_kind": "page",
        }
    if plugin_id == "source.feishu":
        return {
            "space_id": "wiki-space-id",
            "app_id": "env:FEISHU_APP_ID",
            "app_secret": "env:FEISHU_APP_SECRET",
        }
    if plugin_id == "source.database":
        return {
            "engine": "postgresql",
            "source_name": "crm",
            "queries": [{"name": "accounts", "sql": "select id, name from accounts"}],
        }
    return {"workspace": "example"}

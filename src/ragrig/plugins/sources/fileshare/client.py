from __future__ import annotations

import io
import posixpath
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from ragrig.plugins.sources.fileshare.errors import (
    FileshareConfigError,
    FileshareCredentialError,
    FilesharePermanentError,
    FileshareRetryableError,
    FileshareSourceError,
)


@dataclass(frozen=True)
class FileshareFileMetadata:
    path: str
    modified_at: datetime
    size: int
    content_type: str | None
    sample_bytes: bytes = b""
    owner: str | None = None
    group: str | None = None
    permissions: str | None = None


@dataclass(frozen=True)
class FileshareListResult:
    files: list[FileshareFileMetadata]
    next_cursor: str | None = None


@dataclass(frozen=True)
class FakeFileshareObject:
    path: str
    body: bytes
    modified_at: datetime
    content_type: str | None = None
    owner: str | None = None
    group: str | None = None
    permissions: str | None = None


class FileshareClientProtocol(Protocol):
    protocol: str

    def list_files(
        self,
        *,
        root_path: str,
        cursor: str | None,
        page_size: int,
    ) -> FileshareListResult: ...

    def read_file(self, *, path: str) -> bytes: ...


@dataclass
class FakeFileshareClient:
    protocol: str
    host: str | None = None
    share: str | None = None
    base_url: str | None = None
    objects: list[FakeFileshareObject] = field(default_factory=list)
    list_error: Exception | None = None
    read_failures: dict[str, list[Exception]] = field(default_factory=dict)

    def list_files(
        self,
        *,
        root_path: str,
        cursor: str | None,
        page_size: int,
    ) -> FileshareListResult:
        del root_path, page_size
        if self.list_error is not None:
            raise self.list_error
        filtered = sorted(self.objects, key=lambda item: item.path)
        if cursor is not None:
            filtered = [item for item in filtered if item.modified_at.isoformat() >= cursor]
        next_cursor = None
        if filtered:
            next_cursor = max(item.modified_at.isoformat() for item in filtered)
        return FileshareListResult(
            files=[
                FileshareFileMetadata(
                    path=item.path,
                    modified_at=item.modified_at,
                    size=len(item.body),
                    content_type=item.content_type,
                    sample_bytes=item.body[:8192],
                    owner=item.owner,
                    group=item.group,
                    permissions=item.permissions,
                )
                for item in filtered
            ],
            next_cursor=next_cursor,
        )

    def read_file(self, *, path: str) -> bytes:
        failures = self.read_failures.get(path, [])
        if failures:
            raise failures.pop(0)
        for item in self.objects:
            if item.path == path:
                return item.body
        raise FilesharePermanentError(f"file not found: {path}")


def _safe_relative_posix_path(path: str, *, label: str) -> str:
    raw = path.replace("\\", "/").strip()
    if raw.startswith("/"):
        raw = raw.lstrip("/")
    normalized = posixpath.normpath(raw)
    if normalized in {"", "."}:
        return ""
    if normalized == ".." or normalized.startswith("../") or "/../" in f"/{normalized}/":
        raise FilesharePermanentError(f"{label} must be relative and stay within the root")
    return normalized


def _safe_remote_child(parent: str, filename: str) -> tuple[str, str]:
    if "/" in filename or "\\" in filename or filename in {"", ".", ".."}:
        raise FilesharePermanentError("remote filename must be a single safe path segment")
    remote_path = posixpath.normpath(posixpath.join(parent, filename)) if parent else filename
    if parent and not (remote_path == parent or remote_path.startswith(f"{parent}/")):
        raise FilesharePermanentError("remote path escaped the configured root")
    return remote_path, filename


def _webdav_href_path(href: str) -> str:
    parsed = urlsplit(href)
    raw_path = parsed.path if parsed.scheme or parsed.netloc else href
    return posixpath.normpath("/" + raw_path.lstrip("/"))


@dataclass
class MountedPathClient:
    root_path: Path
    protocol: str = "nfs_mounted"

    def list_files(
        self,
        *,
        root_path: str,
        cursor: str | None,
        page_size: int,
    ) -> FileshareListResult:
        del root_path, cursor, page_size
        if not self.root_path.exists() or not self.root_path.is_dir():
            raise FileshareConfigError(
                f"scan root does not exist or is not a directory: {self.root_path}"
            )
        files = []
        for path in sorted(self.root_path.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            files.append(
                FileshareFileMetadata(
                    path=path.relative_to(self.root_path).as_posix(),
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                    size=stat.st_size,
                    content_type=None,
                    sample_bytes=path.read_bytes()[:8192],
                )
            )
        next_cursor = max((item.modified_at.isoformat() for item in files), default=None)
        return FileshareListResult(files=files, next_cursor=next_cursor)

    def read_file(self, *, path: str) -> bytes:
        relative = _safe_relative_posix_path(path, label="mounted file path")
        if not relative:
            raise FilesharePermanentError("mounted file path must not be empty")
        root = self.root_path.resolve()
        target = (root / relative).resolve()
        if target != root and root not in target.parents:
            raise FilesharePermanentError("mounted file path escaped the configured root")
        return target.read_bytes()


@dataclass
class SMBClient:
    host: str
    share: str
    username: str | None = None
    password: str | None = None
    port: int = 445
    protocol: str = "smb"

    def _require_sdk(self) -> None:
        try:
            import smbclient  # noqa: F401
        except ImportError as exc:
            raise FileshareConfigError(
                "smbprotocol is required for SMB support. "
                "Install with: uv pip install 'ragrig[fileshare]'"
            ) from exc

    def _connection_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {"port": self.port}
        if self.username is not None:
            kwargs["username"] = self.username
        if self.password is not None:
            kwargs["password"] = self.password
        return kwargs

    def list_files(
        self,
        *,
        root_path: str,
        cursor: str | None,
        page_size: int,
    ) -> FileshareListResult:
        del page_size
        self._require_sdk()
        import smbclient

        conn_kwargs = self._connection_kwargs()
        base_path = f"\\\\{self.host}\\{self.share}"
        _backslash = "\\"
        safe_root_path = _safe_relative_posix_path(root_path, label="SMB root path")
        scan_root = (
            f"{base_path}\\{safe_root_path.replace('/', _backslash)}"
            if safe_root_path
            else base_path
        )
        files = []
        try:
            smbclient.register_session(
                self.host,
                username=self.username,
                password=self.password,
                port=self.port,
            )
            for entry in smbclient.scandir(scan_root, **conn_kwargs):
                if not entry.is_file():
                    continue
                stat = smbclient.stat(entry.path, port=self.port)
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                if cursor is not None and mtime.isoformat() < cursor:
                    continue
                rel_path = entry.path.removeprefix(scan_root).lstrip("\\").replace("\\", "/")
                files.append(
                    FileshareFileMetadata(
                        path=rel_path,
                        modified_at=mtime,
                        size=stat.st_size,
                        content_type=None,
                        sample_bytes=b"",
                    )
                )
        except Exception as exc:
            self._map_exception(exc)
        files.sort(key=lambda f: f.path)
        next_cursor = max((f.modified_at.isoformat() for f in files), default=None)
        return FileshareListResult(files=files, next_cursor=next_cursor)

    def read_file(self, *, path: str) -> bytes:
        self._require_sdk()
        import smbclient

        conn_kwargs = self._connection_kwargs()
        base_path = f"\\\\{self.host}\\{self.share}"
        _backslash = "\\"
        relative = _safe_relative_posix_path(path, label="SMB file path")
        if not relative:
            raise FilesharePermanentError("SMB file path must not be empty")
        remote_path = f"{base_path}\\{relative.replace('/', _backslash)}"
        try:
            with smbclient.open_file(remote_path, mode="rb", **conn_kwargs) as fh:
                return fh.read()
        except Exception as exc:
            self._map_exception(exc)
            raise FilesharePermanentError(
                f"SMB read failed for {path}: {exc}"
            ) from exc  # pragma: no cover

    def _map_exception(self, exc: Exception) -> None:
        msg = str(exc).lower()
        if "credential" in msg or "authentication" in msg or "logon" in msg:
            raise FileshareCredentialError(str(exc)) from exc
        if "connection" in msg or "timeout" in msg or "refused" in msg:
            raise FileshareRetryableError(str(exc)) from exc
        raise FilesharePermanentError(str(exc)) from exc


@dataclass
class WebDAVClient:
    base_url: str
    username: str | None = None
    password: str | None = None
    protocol: str = "webdav"

    def _require_sdk(self) -> None:
        try:
            import httpx  # noqa: F401
        except ImportError as exc:
            raise FileshareConfigError(
                "httpx is required for WebDAV support. "
                "Install with: uv pip install 'ragrig[fileshare]'"
            ) from exc

    def _client(self):
        import httpx

        auth = None
        if self.username is not None and self.password is not None:
            auth = httpx.BasicAuth(self.username, self.password)
        return httpx.Client(auth=auth, timeout=30)

    def list_files(
        self,
        *,
        root_path: str,
        cursor: str | None,
        page_size: int,
    ) -> FileshareListResult:
        del page_size
        self._require_sdk()
        import httpx

        safe_root_path = _safe_relative_posix_path(root_path, label="WebDAV root path")
        url = self.base_url.rstrip("/") + "/" + safe_root_path
        base_path = posixpath.normpath("/" + urlsplit(self.base_url).path.strip("/"))
        url_path = (
            posixpath.normpath("/" + safe_root_path)
            if base_path == "/"
            else posixpath.normpath(f"{base_path.rstrip('/')}/{safe_root_path}")
        )
        try:
            with self._client() as client:
                response = client.request("PROPFIND", url, headers={"Depth": "1"})
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise FileshareCredentialError(str(exc)) from exc
            raise FilesharePermanentError(str(exc)) from exc
        except httpx.ConnectError as exc:
            raise FileshareRetryableError(str(exc)) from exc
        except Exception as exc:
            raise FilesharePermanentError(str(exc)) from exc

        files = []
        root_tag = "{DAV:}"
        try:
            tree = ET.fromstring(response.text.encode("utf-8"))
        except (ET.ParseError, DefusedXmlException) as exc:
            raise FilesharePermanentError(f"invalid WebDAV PROPFIND response: {exc}") from exc

        for response_elem in tree.findall(f"{root_tag}response"):
            href_elem = response_elem.find(f"{root_tag}href")
            if href_elem is None or href_elem.text is None:
                continue
            href = href_elem.text
            href_path = _webdav_href_path(href)
            # Skip the root directory itself
            if href_path.rstrip("/") == url_path.rstrip("/"):
                continue
            if url_path != "/" and not href_path.startswith(f"{url_path.rstrip('/')}/"):
                continue
            propstat = response_elem.find(f"{root_tag}propstat")
            if propstat is None:
                continue
            prop = propstat.find(f"{root_tag}prop")
            if prop is None:
                continue
            resourcetype = prop.find(f"{root_tag}resourcetype")
            if resourcetype is not None and resourcetype.find(f"{root_tag}collection") is not None:
                continue

            getlastmodified = prop.find(f"{root_tag}getlastmodified")
            getcontentlength = prop.find(f"{root_tag}getcontentlength")
            if getlastmodified is None or getlastmodified.text is None:
                continue
            mtime = self._parse_rfc1123(getlastmodified.text)
            if cursor is not None and mtime.isoformat() < cursor:
                continue
            size = 0
            if getcontentlength is not None and getcontentlength.text is not None:
                size = int(getcontentlength.text)

            try:
                relative_href = (
                    href_path.lstrip("/")
                    if url_path == "/"
                    else href_path.removeprefix(url_path.rstrip("/")).lstrip("/")
                )
                rel_path = _safe_relative_posix_path(
                    relative_href,
                    label="WebDAV response path",
                )
            except FilesharePermanentError:
                continue
            files.append(
                FileshareFileMetadata(
                    path=rel_path,
                    modified_at=mtime,
                    size=size,
                    content_type=None,
                    sample_bytes=b"",
                )
            )

        files.sort(key=lambda f: f.path)
        next_cursor = max((f.modified_at.isoformat() for f in files), default=None)
        return FileshareListResult(files=files, next_cursor=next_cursor)

    def read_file(self, *, path: str) -> bytes:
        self._require_sdk()
        import httpx

        relative = _safe_relative_posix_path(path, label="WebDAV file path")
        if not relative:
            raise FilesharePermanentError("WebDAV file path must not be empty")
        url = self.base_url.rstrip("/") + "/" + relative
        try:
            with self._client() as client:
                response = client.get(url)
                response.raise_for_status()
                return response.content
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise FileshareCredentialError(str(exc)) from exc
            raise FilesharePermanentError(str(exc)) from exc
        except httpx.ConnectError as exc:
            raise FileshareRetryableError(str(exc)) from exc
        except Exception as exc:
            raise FilesharePermanentError(str(exc)) from exc

    @staticmethod
    def _parse_rfc1123(value: str) -> datetime:
        from email.utils import parsedate_to_datetime

        try:
            return parsedate_to_datetime(value).replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)


@dataclass
class SFTPClient:
    host: str
    username: str
    password: str | None = None
    private_key: str | None = None
    port: int = 22
    known_hosts_path: str | None = None
    allow_unknown_host_key: bool = False
    protocol: str = "sftp"

    def _require_sdk(self) -> None:
        try:
            import paramiko  # noqa: F401
        except ImportError as exc:
            raise FileshareConfigError(
                "paramiko is required for SFTP support. "
                "Install with: uv pip install 'ragrig[fileshare]'"
            ) from exc

    def _connect(self):
        import paramiko

        try:
            ssh = paramiko.SSHClient()
            if self.known_hosts_path:
                ssh.load_host_keys(self.known_hosts_path)
            else:
                ssh.load_system_host_keys()
            policy = (
                paramiko.AutoAddPolicy() if self.allow_unknown_host_key else paramiko.RejectPolicy()
            )
            ssh.set_missing_host_key_policy(policy)
            pkey = None
            if self.private_key is not None:
                pkey = paramiko.RSAKey.from_private_key(io.StringIO(self.private_key))
            ssh.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                pkey=pkey,
                look_for_keys=False,
            )
            return _ManagedSFTPClient(ssh.open_sftp(), ssh)
        except paramiko.AuthenticationException as exc:
            raise FileshareCredentialError(str(exc)) from exc
        except paramiko.SSHException as exc:
            msg = str(exc).lower()
            if "connection" in msg or "timeout" in msg or "refused" in msg:
                raise FileshareRetryableError(str(exc)) from exc
            raise FilesharePermanentError(str(exc)) from exc
        except Exception as exc:
            raise FilesharePermanentError(str(exc)) from exc

    def list_files(
        self,
        *,
        root_path: str,
        cursor: str | None,
        page_size: int,
    ) -> FileshareListResult:
        del page_size
        safe_root_path = _safe_relative_posix_path(root_path, label="SFTP root path")
        self._require_sdk()
        sftp = self._connect()
        files = []
        try:
            self._walk_sftp(
                sftp,
                safe_root_path,
                "",
                cursor,
                files,
            )
        except FileshareSourceError:
            raise
        except Exception as exc:
            raise FilesharePermanentError(str(exc)) from exc
        finally:
            sftp.close()
        files.sort(key=lambda f: f.path)
        next_cursor = max((f.modified_at.isoformat() for f in files), default=None)
        return FileshareListResult(files=files, next_cursor=next_cursor)

    def _walk_sftp(
        self,
        sftp,
        root_path: str,
        rel_prefix: str,
        cursor: str | None,
        files: list[FileshareFileMetadata],
    ) -> None:
        import stat

        try:
            for item in sftp.listdir_attr(root_path):
                remote_path, filename = _safe_remote_child(root_path, item.filename)
                rel_path = (
                    _safe_relative_posix_path(
                        f"{rel_prefix}/{filename}".lstrip("/"),
                        label="SFTP relative path",
                    )
                    if rel_prefix
                    else filename
                )
                if stat.S_ISDIR(item.st_mode):
                    self._walk_sftp(sftp, remote_path, rel_path, cursor, files)
                elif stat.S_ISREG(item.st_mode):
                    mtime = datetime.fromtimestamp(item.st_mtime, tz=timezone.utc)
                    if cursor is not None and mtime.isoformat() < cursor:
                        continue
                    files.append(
                        FileshareFileMetadata(
                            path=rel_path,
                            modified_at=mtime,
                            size=item.st_size,
                            content_type=None,
                            sample_bytes=b"",
                        )
                    )
        except IOError as exc:
            raise FilesharePermanentError(str(exc)) from exc

    def read_file(self, *, path: str) -> bytes:
        relative = _safe_relative_posix_path(path, label="SFTP file path")
        if not relative:
            raise FilesharePermanentError("SFTP file path must not be empty")
        self._require_sdk()
        sftp = self._connect()
        try:
            with sftp.file(relative, "rb") as fh:
                return fh.read()
        except FileshareSourceError:
            raise
        except Exception as exc:
            raise FilesharePermanentError(f"SFTP read failed for {path}: {exc}") from exc
        finally:
            sftp.close()


class _ManagedSFTPClient:
    def __init__(self, sftp, ssh_client) -> None:
        self._sftp = sftp
        self._ssh_client = ssh_client

    def __getattr__(self, name: str):
        return getattr(self._sftp, name)

    def close(self) -> None:
        try:
            self._sftp.close()
        finally:
            self._ssh_client.close()

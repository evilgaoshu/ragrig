from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from ragrig.plugins.sources.fileshare.client import (
    SFTPClient,
    SMBClient,
    WebDAVClient,
)
from ragrig.plugins.sources.fileshare.errors import (
    FileshareConfigError,
    FileshareCredentialError,
    FilesharePermanentError,
    FileshareRetryableError,
)


class TestSMBClientMissingSDK:
    def test_require_sdk_raises_when_smbprotocol_missing(self) -> None:
        client = SMBClient(host="localhost", share="share")
        with patch.dict(sys.modules, {"smbclient": None}):
            with pytest.raises(FileshareConfigError, match="smbprotocol is required"):
                client._require_sdk()


class TestSMBClientConnectionKwargs:
    def test_connection_kwargs_no_auth(self) -> None:
        client = SMBClient(host="h", share="s")
        assert client._connection_kwargs() == {"port": 445}

    def test_connection_kwargs_with_auth(self) -> None:
        client = SMBClient(host="h", share="s", username="u", password="p")
        assert client._connection_kwargs() == {"port": 445, "username": "u", "password": "p"}


class TestSMBClientListFiles:
    def test_list_files_success(self) -> None:
        mock_stat = MagicMock()
        mock_stat.st_mtime = 1704067200.0
        mock_stat.st_size = 42

        mock_entry = MagicMock()
        mock_entry.is_file.return_value = True
        mock_entry.path = "\\\\host\\share\\docs\\guide.md"

        client = SMBClient(host="host", share="share")
        with patch.dict(sys.modules, {"smbclient": MagicMock()}):
            mock_smb = sys.modules["smbclient"]
            mock_smb.register_session = MagicMock()
            mock_smb.scandir.return_value = [mock_entry]
            mock_smb.stat.return_value = mock_stat

            result = client.list_files(root_path="docs", cursor=None, page_size=100)

        assert len(result.files) == 1
        assert result.files[0].path == "guide.md"
        assert result.files[0].size == 42

    def test_list_files_skips_dirs(self) -> None:
        mock_entry = MagicMock()
        mock_entry.is_file.return_value = False

        client = SMBClient(host="host", share="share")
        with patch.dict(sys.modules, {"smbclient": MagicMock()}):
            mock_smb = sys.modules["smbclient"]
            mock_smb.register_session = MagicMock()
            mock_smb.scandir.return_value = [mock_entry]

            result = client.list_files(root_path="/", cursor=None, page_size=100)

        assert result.files == []

    def test_list_files_respects_cursor(self) -> None:
        mock_stat = MagicMock()
        mock_stat.st_mtime = 1704067200.0
        mock_stat.st_size = 10

        mock_entry = MagicMock()
        mock_entry.is_file.return_value = True
        mock_entry.path = "\\\\host\\share\\guide.md"

        client = SMBClient(host="host", share="share")
        future_cursor = datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()
        with patch.dict(sys.modules, {"smbclient": MagicMock()}):
            mock_smb = sys.modules["smbclient"]
            mock_smb.register_session = MagicMock()
            mock_smb.scandir.return_value = [mock_entry]
            mock_smb.stat.return_value = mock_stat

            result = client.list_files(root_path="/", cursor=future_cursor, page_size=100)

        assert result.files == []

    def test_list_files_maps_auth_error(self) -> None:
        client = SMBClient(host="host", share="share")
        with patch.dict(sys.modules, {"smbclient": MagicMock()}):
            mock_smb = sys.modules["smbclient"]
            mock_smb.register_session.side_effect = Exception("authentication failed")
            with pytest.raises(FileshareCredentialError):
                client.list_files(root_path="/", cursor=None, page_size=100)

    def test_list_files_maps_connection_error(self) -> None:
        client = SMBClient(host="host", share="share")
        with patch.dict(sys.modules, {"smbclient": MagicMock()}):
            mock_smb = sys.modules["smbclient"]
            mock_smb.register_session.side_effect = Exception("connection refused")
            with pytest.raises(FileshareRetryableError):
                client.list_files(root_path="/", cursor=None, page_size=100)


class TestSMBClientReadFile:
    def test_read_file_success(self) -> None:
        mock_fh = MagicMock()
        mock_fh.read.return_value = b"hello"
        mock_fh.__enter__ = MagicMock(return_value=mock_fh)
        mock_fh.__exit__ = MagicMock(return_value=False)

        client = SMBClient(host="host", share="share")
        with patch.dict(sys.modules, {"smbclient": MagicMock()}):
            mock_smb = sys.modules["smbclient"]
            mock_smb.open_file.return_value = mock_fh

            result = client.read_file(path="guide.md")

        assert result == b"hello"

    def test_read_file_maps_auth_error(self) -> None:
        client = SMBClient(host="host", share="share")
        with patch.dict(sys.modules, {"smbclient": MagicMock()}):
            mock_smb = sys.modules["smbclient"]
            mock_smb.open_file.side_effect = Exception("logon failure")
            with pytest.raises(FileshareCredentialError):
                client.read_file(path="guide.md")

    def test_read_file_maps_connection_error(self) -> None:
        client = SMBClient(host="host", share="share")
        with patch.dict(sys.modules, {"smbclient": MagicMock()}):
            mock_smb = sys.modules["smbclient"]
            mock_smb.open_file.side_effect = Exception("timeout")
            with pytest.raises(FileshareRetryableError):
                client.read_file(path="guide.md")

    def test_read_file_maps_other_error(self) -> None:
        client = SMBClient(host="host", share="share")
        with patch.dict(sys.modules, {"smbclient": MagicMock()}):
            mock_smb = sys.modules["smbclient"]
            mock_smb.open_file.side_effect = Exception("unknown")
            with pytest.raises(FilesharePermanentError):
                client.read_file(path="guide.md")

    def test_read_file_re_raises_fileshare_source_error(self) -> None:
        client = SMBClient(host="host", share="share")
        with patch.dict(sys.modules, {"smbclient": MagicMock()}):
            mock_smb = sys.modules["smbclient"]
            mock_smb.open_file.side_effect = FilesharePermanentError("boom")
            with pytest.raises(FilesharePermanentError, match="boom"):
                client.read_file(path="guide.md")


class TestSMBClientErrorMapping:
    def test_map_exception_raises_credential_error_for_auth(self) -> None:
        client = SMBClient(host="localhost", share="share")
        with pytest.raises(FileshareCredentialError):
            client._map_exception(Exception("authentication failed"))

    def test_map_exception_raises_retryable_for_connection(self) -> None:
        client = SMBClient(host="localhost", share="share")
        with pytest.raises(FileshareRetryableError):
            client._map_exception(Exception("connection refused"))

    def test_map_exception_raises_permanent_for_other(self) -> None:
        client = SMBClient(host="localhost", share="share")
        with pytest.raises(FilesharePermanentError):
            client._map_exception(Exception("some other error"))


class TestWebDAVClientRequireSDK:
    def test_require_sdk_raises_when_httpx_missing(self) -> None:
        client = WebDAVClient(base_url="http://localhost")
        with patch.dict(sys.modules, {"httpx": None}):
            with pytest.raises(FileshareConfigError, match="httpx is required"):
                client._require_sdk()


class TestWebDAVClientListFiles:
    def test_list_files_parses_propfind_response(self) -> None:
        mock_response = MagicMock()
        mock_response.text = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype><D:collection/></D:resourcetype>
        <D:getlastmodified>Mon, 01 Jan 2024 00:00:00 GMT</D:getlastmodified>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
  <D:response>
    <D:href>/guide.md</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype/>
        <D:getlastmodified>Mon, 01 Jan 2024 00:00:00 GMT</D:getlastmodified>
        <D:getcontentlength>31</D:getcontentlength>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>
"""
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            result = client.list_files(root_path="/", cursor=None, page_size=100)

        assert len(result.files) == 1
        assert result.files[0].path == "guide.md"
        assert result.files[0].size == 31

    def test_list_files_maps_401_to_credential_error(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 401
        error = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=mock_response
        )
        mock_response.raise_for_status.side_effect = error

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            with pytest.raises(FileshareCredentialError):
                client.list_files(root_path="/", cursor=None, page_size=100)

    def test_list_files_maps_500_to_permanent_error(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        error = httpx.HTTPStatusError("500 Error", request=MagicMock(), response=mock_response)
        mock_response.raise_for_status.side_effect = error

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            with pytest.raises(FilesharePermanentError):
                client.list_files(root_path="/", cursor=None, page_size=100)

    def test_list_files_maps_connect_error_to_retryable(self) -> None:
        mock_client = MagicMock()
        mock_client.request.side_effect = httpx.ConnectError("connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            with pytest.raises(FileshareRetryableError):
                client.list_files(root_path="/", cursor=None, page_size=100)

    def test_list_files_maps_other_error_to_permanent(self) -> None:
        mock_client = MagicMock()
        mock_client.request.side_effect = ValueError("boom")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            with pytest.raises(FilesharePermanentError):
                client.list_files(root_path="/", cursor=None, page_size=100)

    def test_list_files_skips_missing_href(self) -> None:
        mock_response = MagicMock()
        mock_response.text = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:propstat>
      <D:prop>
        <D:resourcetype/>
        <D:getlastmodified>Mon, 01 Jan 2024 00:00:00 GMT</D:getlastmodified>
      </D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>
"""
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            result = client.list_files(root_path="/", cursor=None, page_size=100)

        assert result.files == []

    def test_list_files_skips_missing_propstat(self) -> None:
        mock_response = MagicMock()
        mock_response.text = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/guide.md</D:href>
  </D:response>
</D:multistatus>
"""
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            result = client.list_files(root_path="/", cursor=None, page_size=100)

        assert result.files == []

    def test_list_files_skips_missing_prop(self) -> None:
        mock_response = MagicMock()
        mock_response.text = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/guide.md</D:href>
    <D:propstat>
    </D:propstat>
  </D:response>
</D:multistatus>
"""
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            result = client.list_files(root_path="/", cursor=None, page_size=100)

        assert result.files == []

    def test_list_files_skips_collection(self) -> None:
        mock_response = MagicMock()
        mock_response.text = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/subdir</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype><D:collection/></D:resourcetype>
        <D:getlastmodified>Mon, 01 Jan 2024 00:00:00 GMT</D:getlastmodified>
      </D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>
"""
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            result = client.list_files(root_path="/", cursor=None, page_size=100)

        assert result.files == []

    def test_list_files_invalid_xml_raises_permanent(self) -> None:
        mock_response = MagicMock()
        mock_response.text = "not xml"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            with pytest.raises(FilesharePermanentError, match="invalid WebDAV"):
                client.list_files(root_path="/", cursor=None, page_size=100)

    def test_list_files_missing_modified_skips(self) -> None:
        mock_response = MagicMock()
        mock_response.text = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/guide.md</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype/>
        <D:getcontentlength>31</D:getcontentlength>
      </D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>
"""
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            result = client.list_files(root_path="/", cursor=None, page_size=100)

        assert result.files == []

    def test_list_files_respects_cursor(self) -> None:
        mock_response = MagicMock()
        mock_response.text = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/guide.md</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype/>
        <D:getlastmodified>Mon, 01 Jan 2024 00:00:00 GMT</D:getlastmodified>
        <D:getcontentlength>31</D:getcontentlength>
      </D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>
"""
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        future_cursor = datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()
        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            result = client.list_files(root_path="/", cursor=future_cursor, page_size=100)

        assert result.files == []


class TestWebDAVClientReadFile:
    def test_read_file_returns_content(self) -> None:
        mock_response = MagicMock()
        mock_response.content = b"# Guide\n"
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            result = client.read_file(path="guide.md")

        assert result == b"# Guide\n"

    def test_read_file_maps_connect_error_to_retryable(self) -> None:
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            with pytest.raises(FileshareRetryableError):
                client.read_file(path="guide.md")

    def test_read_file_maps_403_to_credential_error(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=mock_response
        )
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            with pytest.raises(FileshareCredentialError):
                client.read_file(path="guide.md")

    def test_read_file_maps_other_to_permanent(self) -> None:
        mock_client = MagicMock()
        mock_client.get.side_effect = ValueError("boom")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            with pytest.raises(FilesharePermanentError):
                client.read_file(path="guide.md")

    def test_read_file_maps_500_to_permanent(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_response
        )
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            client = WebDAVClient(base_url="http://localhost:8080")
            with pytest.raises(FilesharePermanentError):
                client.read_file(path="guide.md")


class TestWebDAVClientAuth:
    def test_client_uses_basic_auth_when_credentials_set(self) -> None:
        with patch("httpx.Client") as mock_cls:
            client = WebDAVClient(base_url="http://localhost", username="u", password="p")
            client._client()
            _, kwargs = mock_cls.call_args
            assert kwargs["auth"] is not None

    def test_client_uses_no_auth_when_credentials_missing(self) -> None:
        with patch("httpx.Client") as mock_cls:
            client = WebDAVClient(base_url="http://localhost")
            client._client()
            _, kwargs = mock_cls.call_args
            assert kwargs["auth"] is None


class TestWebDAVClientParseRFC1123:
    def test_parse_valid_date(self) -> None:
        dt = WebDAVClient._parse_rfc1123("Mon, 01 Jan 2024 00:00:00 GMT")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1

    def test_parse_invalid_date_returns_now(self) -> None:
        dt = WebDAVClient._parse_rfc1123("not a date")
        assert dt.tzinfo is not None


class TestSFTPClientMissingSDK:
    def test_require_sdk_raises_when_paramiko_missing(self) -> None:
        client = SFTPClient(host="localhost", username="u")
        with patch.dict(sys.modules, {"paramiko": None}):
            with pytest.raises(FileshareConfigError, match="paramiko is required"):
                client._require_sdk()


class TestSFTPClientConnect:
    def test_connect_with_password(self) -> None:
        mock_transport = MagicMock()
        mock_sftp = MagicMock()

        client = SFTPClient(host="host", username="u", password="p")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            mock_paramiko = sys.modules["paramiko"]
            mock_paramiko.Transport.return_value = mock_transport
            mock_paramiko.SFTPClient.from_transport.return_value = mock_sftp

            result = client._connect()

        assert result == mock_sftp
        mock_transport.connect.assert_called_once_with(username="u", password="p", pkey=None)

    def test_connect_with_private_key(self) -> None:
        mock_transport = MagicMock()
        mock_sftp = MagicMock()
        mock_pkey = MagicMock()

        client = SFTPClient(host="host", username="u", private_key="KEY")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            mock_paramiko = sys.modules["paramiko"]
            mock_paramiko.Transport.return_value = mock_transport
            mock_paramiko.SFTPClient.from_transport.return_value = mock_sftp
            mock_paramiko.RSAKey.from_private_key.return_value = mock_pkey

            result = client._connect()

        assert result == mock_sftp
        mock_transport.connect.assert_called_once_with(username="u", password=None, pkey=mock_pkey)

    def test_connect_maps_auth_exception(self) -> None:
        client = SFTPClient(host="host", username="u")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            mock_paramiko = sys.modules["paramiko"]
            mock_paramiko.Transport.side_effect = Exception("auth failed")
            # Simulate AuthenticationException path by checking exception type
            mock_paramiko.AuthenticationException = Exception
            with pytest.raises(FileshareCredentialError):
                client._connect()

    def test_connect_maps_ssh_connection_error(self) -> None:
        client = SFTPClient(host="host", username="u")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            mock_paramiko = sys.modules["paramiko"]
            SSHException = type("SSHException", (Exception,), {})
            mock_paramiko.Transport.side_effect = SSHException("connection refused")
            mock_paramiko.AuthenticationException = type(
                "AuthenticationException", (Exception,), {}
            )
            mock_paramiko.SSHException = SSHException
            with pytest.raises(FileshareRetryableError):
                client._connect()

    def test_connect_maps_other_error(self) -> None:
        client = SFTPClient(host="host", username="u")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            mock_paramiko = sys.modules["paramiko"]
            mock_paramiko.Transport.side_effect = ValueError("boom")
            mock_paramiko.AuthenticationException = type(
                "AuthenticationException", (Exception,), {}
            )
            mock_paramiko.SSHException = type("SSHException", (Exception,), {})
            with pytest.raises(FilesharePermanentError):
                client._connect()

    def test_connect_maps_ssh_non_connection_error(self) -> None:
        client = SFTPClient(host="host", username="u")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            mock_paramiko = sys.modules["paramiko"]
            SSHException = type("SSHException", (Exception,), {})
            mock_paramiko.Transport.side_effect = SSHException("some ssh error")
            mock_paramiko.AuthenticationException = type(
                "AuthenticationException", (Exception,), {}
            )
            mock_paramiko.SSHException = SSHException
            with pytest.raises(FilesharePermanentError):
                client._connect()


class TestSFTPClientListFiles:
    def test_list_files_success(self) -> None:
        mock_sftp = MagicMock()
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100644
        mock_stat.st_mtime = 1704067200.0
        mock_stat.st_size = 42
        mock_stat.filename = "guide.md"

        mock_sftp.listdir_attr.return_value = [mock_stat]

        client = SFTPClient(host="host", username="u")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            with patch.object(client, "_connect", return_value=mock_sftp):
                result = client.list_files(root_path="/docs", cursor=None, page_size=100)

        assert len(result.files) == 1
        assert result.files[0].path == "guide.md"
        mock_sftp.close.assert_called_once()

    def test_list_files_respects_cursor(self) -> None:
        mock_sftp = MagicMock()
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100644
        mock_stat.st_mtime = 1704067200.0
        mock_stat.st_size = 42
        mock_stat.filename = "guide.md"

        mock_sftp.listdir_attr.return_value = [mock_stat]

        client = SFTPClient(host="host", username="u")
        future_cursor = datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            with patch.object(client, "_connect", return_value=mock_sftp):
                result = client.list_files(root_path="/docs", cursor=future_cursor, page_size=100)

        assert result.files == []
        mock_sftp.close.assert_called_once()

    def test_list_files_walks_subdirs(self) -> None:
        mock_sftp = MagicMock()
        dir_stat = MagicMock()
        dir_stat.st_mode = 0o040755
        dir_stat.filename = "subdir"
        file_stat = MagicMock()
        file_stat.st_mode = 0o100644
        file_stat.st_mtime = 1704067200.0
        file_stat.st_size = 10
        file_stat.filename = "nested.md"

        def side_effect(path):
            if path == "docs":
                return [dir_stat]
            if path == "docs/subdir":
                return [file_stat]
            return []

        mock_sftp.listdir_attr.side_effect = side_effect

        client = SFTPClient(host="host", username="u")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            with patch.object(client, "_connect", return_value=mock_sftp):
                result = client.list_files(root_path="/docs", cursor=None, page_size=100)

        assert len(result.files) == 1
        assert result.files[0].path == "subdir/nested.md"

    def test_list_files_raises_on_ioerror(self) -> None:
        mock_sftp = MagicMock()
        mock_sftp.listdir_attr.side_effect = IOError("permission denied")

        client = SFTPClient(host="host", username="u")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            with patch.object(client, "_connect", return_value=mock_sftp):
                with pytest.raises(FilesharePermanentError):
                    client.list_files(root_path="/docs", cursor=None, page_size=100)

    def test_list_files_raises_on_generic_exception(self) -> None:
        mock_sftp = MagicMock()
        mock_sftp.listdir_attr.side_effect = ValueError("unexpected")

        client = SFTPClient(host="host", username="u")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            with patch.object(client, "_connect", return_value=mock_sftp):
                with pytest.raises(FilesharePermanentError):
                    client.list_files(root_path="/docs", cursor=None, page_size=100)


class TestSFTPClientReadFile:
    def test_read_file_success(self) -> None:
        mock_sftp = MagicMock()
        mock_fh = MagicMock()
        mock_fh.read.return_value = b"hello"
        mock_fh.__enter__ = MagicMock(return_value=mock_fh)
        mock_fh.__exit__ = MagicMock(return_value=False)
        mock_sftp.file.return_value = mock_fh

        client = SFTPClient(host="host", username="u")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            with patch.object(client, "_connect", return_value=mock_sftp):
                result = client.read_file(path="/docs/guide.md")

        assert result == b"hello"
        mock_sftp.close.assert_called_once()

    def test_read_file_maps_error(self) -> None:
        mock_sftp = MagicMock()
        mock_sftp.file.side_effect = IOError("read failed")

        client = SFTPClient(host="host", username="u")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            with patch.object(client, "_connect", return_value=mock_sftp):
                with pytest.raises(FilesharePermanentError, match="SFTP read failed"):
                    client.read_file(path="/docs/guide.md")

        mock_sftp.close.assert_called_once()

    def test_read_file_re_raises_fileshare_source_error(self) -> None:
        mock_sftp = MagicMock()
        mock_sftp.file.side_effect = FileshareCredentialError("bad creds")

        client = SFTPClient(host="host", username="u")
        with patch.dict(sys.modules, {"paramiko": MagicMock()}):
            with patch.object(client, "_connect", return_value=mock_sftp):
                with pytest.raises(FileshareCredentialError, match="bad creds"):
                    client.read_file(path="/docs/guide.md")

        mock_sftp.close.assert_called_once()

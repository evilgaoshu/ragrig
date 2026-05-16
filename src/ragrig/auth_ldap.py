"""LDAP authentication connector.

Performs a service-account search to resolve the user DN, then validates
credentials by binding as that user. Supports StartTLS.
"""

from __future__ import annotations

from dataclasses import dataclass

import ldap3
import ldap3.core.exceptions as ldap_exc

from ragrig.config import Settings


@dataclass(frozen=True)
class LdapUserInfo:
    dn: str
    uid: str  # value of the email attribute — used as external_auth_uid
    email: str
    display_name: str
    groups: list[str]  # raw group DNs from memberOf


class LdapAuthError(Exception):
    """Raised when LDAP auth fails for any reason."""


def _server(settings: Settings) -> ldap3.Server:
    return ldap3.Server(
        settings.ragrig_ldap_url,
        use_ssl=settings.ragrig_ldap_url.startswith("ldaps://"),
        get_info=ldap3.NONE,
    )


def _build_filter(template: str, login: str) -> str:
    escaped = ldap3.utils.conv.escape_filter_chars(login)
    return template.replace("{login}", escaped)


def authenticate_ldap(login: str, password: str, settings: Settings) -> LdapUserInfo:
    """Verify *login* / *password* against the configured LDAP directory.

    Steps:
    1. Bind with the service account to search for the user DN.
    2. Attempt a bind with the resolved DN and the supplied password.
    3. Return structured user info if successful; raise LdapAuthError otherwise.
    """
    if not settings.ragrig_ldap_enabled:
        raise LdapAuthError("LDAP authentication is not enabled")
    if not password:
        raise LdapAuthError("password must not be empty")

    server = _server(settings)

    # Step 1: service-account bind + user search
    try:
        svc_conn = ldap3.Connection(
            server,
            user=settings.ragrig_ldap_bind_dn,
            password=settings.ragrig_ldap_bind_password,
            auto_bind=ldap3.AUTO_BIND_NONE,
        )
        if settings.ragrig_ldap_use_tls and not settings.ragrig_ldap_url.startswith("ldaps://"):
            svc_conn.start_tls()
        svc_conn.bind()
        if not svc_conn.bound:
            raise LdapAuthError("LDAP service account bind failed")
    except ldap_exc.LDAPException as exc:
        raise LdapAuthError(f"LDAP service bind error: {exc}") from exc

    search_filter = _build_filter(settings.ragrig_ldap_user_filter, login)
    attrs = [
        settings.ragrig_ldap_attr_email,
        settings.ragrig_ldap_attr_display_name,
        settings.ragrig_ldap_attr_groups,
    ]
    svc_conn.search(
        settings.ragrig_ldap_search_base,
        search_filter,
        attributes=attrs,
    )
    entries = svc_conn.entries
    svc_conn.unbind()

    if not entries:
        raise LdapAuthError("user not found in directory")
    if len(entries) > 1:
        raise LdapAuthError("ambiguous user: multiple directory entries matched")

    entry = entries[0]
    user_dn = entry.entry_dn

    # Step 2: bind as the user to verify the password
    try:
        user_conn = ldap3.Connection(
            server,
            user=user_dn,
            password=password,
            auto_bind=ldap3.AUTO_BIND_NONE,
        )
        if settings.ragrig_ldap_use_tls and not settings.ragrig_ldap_url.startswith("ldaps://"):
            user_conn.start_tls()
        user_conn.bind()
        bound = user_conn.bound
        user_conn.unbind()
    except ldap_exc.LDAPException as exc:
        raise LdapAuthError(f"LDAP user bind error: {exc}") from exc

    if not bound:
        raise LdapAuthError("invalid credentials")

    def _attr(name: str) -> str:
        val = getattr(entry, name, None)
        if val is None:
            return ""
        return str(val) if not isinstance(val, list) else (str(val[0]) if val else "")

    def _attr_list(name: str) -> list[str]:
        val = getattr(entry, name, None)
        if val is None:
            return []
        if isinstance(val, list):
            return [str(v) for v in val]
        return [str(val)]

    email = _attr(settings.ragrig_ldap_attr_email) or login
    display_name = _attr(settings.ragrig_ldap_attr_display_name) or email.split("@")[0]
    groups = _attr_list(settings.ragrig_ldap_attr_groups)

    return LdapUserInfo(
        dn=user_dn,
        uid=user_dn,
        email=email,
        display_name=display_name,
        groups=groups,
    )

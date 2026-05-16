"""SMTP email delivery for RAGRig.

Sends transactional emails (currently: workspace invitations).
Disabled when RAGRIG_SMTP_ENABLED=false (default).
"""

from __future__ import annotations

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ragrig.config import Settings


class EmailDeliveryError(Exception):
    """Raised when email delivery fails."""


def send_invitation_email(
    settings: Settings,
    *,
    to_email: str,
    workspace_name: str,
    inviter_name: str | None,
    role: str,
    token: str,
    expires_days: int,
) -> None:
    """Send a workspace invitation email.

    No-ops when RAGRIG_SMTP_ENABLED is False.
    Raises EmailDeliveryError on SMTP failure.
    """
    if not settings.ragrig_smtp_enabled:
        return

    accept_url = f"{settings.ragrig_app_base_url.rstrip('/')}/register?invitation_token={token}"
    inviter_label = inviter_name or "A workspace administrator"
    subject = f"You're invited to join {workspace_name} on RAGRig"
    body_text = (
        f"{inviter_label} has invited you to join {workspace_name} as {role}.\n\n"
        f"Accept your invitation (valid for {expires_days} days):\n{accept_url}\n\n"
        "If you did not expect this email, you can safely ignore it."
    )
    body_html = f"""\
<html><body>
<p>{inviter_label} has invited you to join <strong>{workspace_name}</strong>
as <strong>{role}</strong>.</p>
<p><a href="{accept_url}">Accept invitation</a> (valid for {expires_days} days)</p>
<p style="color:#888;font-size:12px">If you did not expect this email, you can safely ignore it.</p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.ragrig_smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    _send(settings, to_email, msg)


def _send(settings: Settings, to_email: str, msg: MIMEMultipart) -> None:
    try:
        if settings.ragrig_smtp_use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(settings.ragrig_smtp_host, settings.ragrig_smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                if settings.ragrig_smtp_username:
                    smtp.login(settings.ragrig_smtp_username, settings.ragrig_smtp_password)
                smtp.sendmail(settings.ragrig_smtp_from, to_email, msg.as_string())
        else:
            with smtplib.SMTP(settings.ragrig_smtp_host, settings.ragrig_smtp_port) as smtp:
                if settings.ragrig_smtp_username:
                    smtp.login(settings.ragrig_smtp_username, settings.ragrig_smtp_password)
                smtp.sendmail(settings.ragrig_smtp_from, to_email, msg.as_string())
    except Exception as exc:
        raise EmailDeliveryError(f"Failed to send email to {to_email}: {exc}") from exc

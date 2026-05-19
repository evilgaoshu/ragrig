from __future__ import annotations

import email
import email.policy
import hashlib
import html
import re
from pathlib import Path
from typing import Any

from ragrig.parsers.base import ParseResult, TextFileParser
from ragrig.parsers.sanitizer import sanitize_text_summary


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    return html.unescape(text)


def _decode_part(part: Any) -> str:
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, Exception):
        return payload.decode("utf-8", errors="replace")


def _extract_body(msg: Any) -> str:
    parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            if ct == "text/plain":
                parts.append(_decode_part(part))
            elif ct == "text/html" and not parts:
                parts.append(_strip_html(_decode_part(part)))
    else:
        text = _decode_part(msg)
        if msg.get_content_type() == "text/html":
            text = _strip_html(text)
        parts.append(text)
    return "\n\n".join(p for p in parts if p.strip())


class EmailParser(TextFileParser):
    parser_name = "email"
    mime_type = "message/rfc822"

    SUPPORTED_EXTENSIONS = frozenset({".eml", ".msg"})

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()

        try:
            msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)
        except Exception as exc:
            summary, redactions = sanitize_text_summary("")
            return ParseResult(
                extracted_text="",
                content_hash=content_hash,
                mime_type=self.mime_type,
                parser_name=self.parser_name,
                metadata={
                    "parser_id": "parser.email",
                    "status": "error",
                    "error": str(exc),
                    "extension": path.suffix.lower(),
                    "text_summary": summary,
                    "redaction_count": redactions,
                },
            )

        subject = str(msg.get("Subject", ""))
        sender = str(msg.get("From", ""))
        recipients = str(msg.get("To", ""))
        date = str(msg.get("Date", ""))
        body = _extract_body(msg)

        header_block = "\n".join(
            part
            for part in [
                f"From: {sender}" if sender else "",
                f"To: {recipients}" if recipients else "",
                f"Date: {date}" if date else "",
                f"Subject: {subject}" if subject else "",
            ]
            if part
        )
        extracted_text = f"{header_block}\n\n{body}".strip()
        summary, redactions = sanitize_text_summary(extracted_text)

        return ParseResult(
            extracted_text=extracted_text,
            content_hash=content_hash,
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata={
                "parser_id": "parser.email",
                "status": "success",
                "extension": path.suffix.lower(),
                "subject": subject,
                "sender": sender,
                "recipients": recipients,
                "date": date,
                "char_count": len(extracted_text),
                "byte_count": len(raw_bytes),
                "text_summary": summary,
                "redaction_count": redactions,
            },
        )

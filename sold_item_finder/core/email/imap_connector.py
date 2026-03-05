from __future__ import annotations

import email
import imaplib
from datetime import datetime, timedelta
from email.utils import getaddresses
from email.header import decode_header, make_header
from email.message import Message
from email import policy

from sold_item_finder.core.email.connector_base import EmailConnector
from sold_item_finder.core.email.models import EmailMessage, EmailSettings


class ImapEmailConnector(EmailConnector):
    def __init__(self) -> None:
        self._client: imaplib.IMAP4_SSL | None = None
        self._settings: EmailSettings | None = None

    def connect(self, settings: EmailSettings, secret: str) -> None:
        self._settings = settings
        self._client = imaplib.IMAP4_SSL(settings.host, settings.port)
        self._client.login(settings.username, secret)
        self._client.select(settings.mailbox)

    def fetch_messages(self, cancel_flag: callable | None = None) -> list[EmailMessage]:
        if not self._client or not self._settings:
            raise RuntimeError("Connector is not connected")
        settings = self._settings
        since_date = (datetime.now() - timedelta(days=settings.search_window_days)).strftime("%d-%b-%Y")
        status, data = self._client.search(None, "SINCE", since_date)
        if status != "OK":
            return []
        ids = data[0].split()[-settings.max_messages :]
        messages: list[EmailMessage] = []
        unfiltered_messages: list[EmailMessage] = []
        for msg_id in reversed(ids):
            if cancel_flag and cancel_flag():
                break
            status_h, fetched_h = self._client.fetch(msg_id, "(BODY.PEEK[HEADER])")
            if status_h != "OK" or not fetched_h:
                continue
            status_t, fetched_t = self._client.fetch(msg_id, "(BODY.PEEK[TEXT]<0.512>)")
            snippet_bytes = b""
            if status_t == "OK" and fetched_t:
                for chunk in fetched_t:
                    if isinstance(chunk, tuple):
                        snippet_bytes += chunk[1] or b""

            header_bytes = b""
            for chunk in fetched_h:
                if isinstance(chunk, tuple) and chunk[1]:
                    header_bytes += chunk[1]
            if not header_bytes:
                continue
            parsed = email.message_from_bytes(header_bytes or b"", policy=policy.default)
            to_field = parsed.get("to", "")
            cc_field = parsed.get("cc", "")
            delivered_to = (
                parsed.get("delivered-to", "")
                or parsed.get("x-original-to", "")
                or parsed.get("x-forwarded-to", "")
                or parsed.get("envelope-to", "")
            )
            subject = _decode_header(parsed.get("subject", ""))
            from_address = parsed.get("from", "")
            date = parsed.get("date", "")
            headers = str(parsed)
            snippet = _snippet_from_message(parsed) or snippet_bytes.decode("utf-8", errors="ignore")
            message = EmailMessage(
                message_id=msg_id.decode("utf-8", errors="ignore"),
                date=date,
                from_address=from_address,
                to_address=to_field,
                subject=subject,
                snippet=snippet[:400],
                raw_headers=headers[:5000],
            )
            unfiltered_messages.append(message)
            if _contains_target([to_field, cc_field, delivered_to], settings.target_to_address):
                messages.append(message)
        if settings.target_to_address and not messages:
            # Fail-open for mailbox usability when providers omit recipient headers.
            return unfiltered_messages
        return messages

    def disconnect(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            try:
                self._client.logout()
            except Exception:
                pass
        self._client = None


def _contains_target(headers: list[str], target: str) -> bool:
    t = target.strip().lower()
    if not t:
        return True
    addresses = [addr.lower() for _, addr in getaddresses(headers)]
    if any(addr == t for addr in addresses):
        return True
    return any(t in (h or "").lower() for h in headers)


def _decode_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _snippet_from_message(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")

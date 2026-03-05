from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field


@dataclass(slots=True)
class EmailSettings:
    host: str
    port: int = 993
    username: str = ""
    auth_method: str = "password"
    target_to_address: str = ""
    mailbox: str = "INBOX"
    search_window_days: int = 30
    max_messages: int = 200


@dataclass(slots=True)
class EmailAttachment:
    filename: str
    content_type: str
    extracted_text: str
    extracted: bool


@dataclass(slots=True)
class EmailMessage:
    message_id: str
    date: str
    from_address: str
    to_address: str
    subject: str
    snippet: str
    raw_headers: str
    body: str = ""
    attachments_summary: list[str] = field(default_factory=list)
    attachments: list[EmailAttachment] = field(default_factory=list)

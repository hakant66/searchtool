from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from sold_item_finder.core.email.models import EmailAttachment, EmailMessage, EmailSettings


class EmailMcpClient:
    def __init__(self) -> None:
        self.server_cmd = [sys.executable, "-m", "mcp_email_server.server"]

    def test_connection(self, settings: EmailSettings, secret: str) -> dict[str, Any]:
        payload = self._base_payload(settings, secret)
        return self._call_tool("email.test_connection", payload)

    def fetch_messages(self, settings: EmailSettings, secret: str) -> tuple[list[EmailMessage], dict[str, Any]]:
        payload = self._base_payload(settings, secret)
        payload.update(
            {
                "window_days": settings.search_window_days,
                "max_messages": settings.max_messages,
                "target_to_address": settings.target_to_address,
            }
        )
        result = self._call_tool("email.fetch_messages", payload)
        messages = [
            EmailMessage(
                message_id=str(item.get("message_id", "")),
                date=str(item.get("date", "")),
                from_address=str(item.get("from_address", "")),
                to_address=str(item.get("to_address", "")),
                subject=str(item.get("subject", "")),
                snippet=str(item.get("snippet", "")),
                raw_headers=str(item.get("raw_headers", "")),
                body=str(item.get("body", "")),
                attachments_summary=[str(v) for v in item.get("attachments_summary", [])],
                attachments=[
                    EmailAttachment(
                        filename=str(att.get("filename", "")),
                        content_type=str(att.get("content_type", "")),
                        extracted_text=str(att.get("extracted_text", "")),
                        extracted=bool(att.get("extracted", False)),
                    )
                    for att in item.get("attachments", [])
                ],
            )
            for item in result.get("messages", [])
        ]
        return messages, dict(result.get("debug", {}))

    def _base_payload(self, settings: EmailSettings, secret: str) -> dict[str, Any]:
        return {
            "host": settings.host,
            "port": settings.port,
            "username": settings.username,
            "password": secret,
            "mailbox": settings.mailbox,
        }

    def _call_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        cmd = [
            *self.server_cmd,
            "--tool",
            tool_name,
            "--args-json",
            json.dumps(args),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"MCP server call failed: {tool_name}")
        output = proc.stdout.strip()
        if not output:
            return {}
        return json.loads(output)

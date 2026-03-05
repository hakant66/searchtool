from __future__ import annotations

import argparse
import email
from email import policy
from email.header import decode_header, make_header
from email.utils import getaddresses
import imaplib
import json
import sys
from datetime import datetime, timedelta
from typing import Any

from mcp_email_server.attachment_reader import extract_attachment_text


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "email.test_connection": {
        "name": "email.test_connection",
        "description": "Validate IMAP connectivity and credentials.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "mailbox": {"type": "string"},
            },
            "required": ["host", "port", "username", "password"],
        },
    },
    "email.fetch_messages": {
        "name": "email.fetch_messages",
        "description": "Fetch recent emails with body and supported attachment text extraction.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "mailbox": {"type": "string"},
                "window_days": {"type": "integer"},
                "max_messages": {"type": "integer"},
                "target_to_address": {"type": "string"},
            },
            "required": ["host", "port", "username", "password"],
        },
    },
}


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "email.test_connection":
        return _test_connection(args)
    if name == "email.fetch_messages":
        return _fetch_messages(args)
    raise ValueError(f"Unknown tool: {name}")


def _test_connection(args: dict[str, Any]) -> dict[str, Any]:
    mailbox = args.get("mailbox", "INBOX")
    client = imaplib.IMAP4_SSL(args["host"], int(args["port"]))
    try:
        client.login(args["username"], args["password"])
        client.select(mailbox)
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.logout()
        except Exception:
            pass
    return {"ok": True, "message": "Connection successful"}


def _fetch_messages(args: dict[str, Any]) -> dict[str, Any]:
    mailbox = args.get("mailbox", "INBOX")
    window_days = int(args.get("window_days", 30))
    max_messages = int(args.get("max_messages", 200))
    target = str(args.get("target_to_address", "") or "").strip().lower()

    client = imaplib.IMAP4_SSL(args["host"], int(args["port"]))
    try:
        client.login(args["username"], args["password"])
        client.select(mailbox)
        since_date = (datetime.now() - timedelta(days=window_days)).strftime("%d-%b-%Y")
        status, data = client.search(None, "SINCE", since_date)
        if status != "OK":
            return {"messages": [], "count": 0, "filter_applied": bool(target)}
        ids = data[0].split()[-max_messages:]
        unfiltered: list[dict[str, Any]] = []
        filtered: list[dict[str, Any]] = []
        for msg_id in reversed(ids):
            status, fetched = client.fetch(msg_id, "(RFC822)")
            if status != "OK" or not fetched:
                continue
            raw = b""
            for chunk in fetched:
                if isinstance(chunk, tuple) and chunk[1]:
                    raw += chunk[1]
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=policy.default)
            model = _email_to_model(msg, msg_id.decode("utf-8", errors="ignore"))
            unfiltered.append(model)
            if _contains_target(msg, target):
                filtered.append(model)
        messages = filtered if filtered else unfiltered
        return {
            "messages": messages,
            "count": len(messages),
            "filter_applied": bool(target),
            "debug": {
                "candidate_count": len(unfiltered),
                "post_filter_count": len(filtered),
                "mailbox": mailbox,
            },
        }
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.logout()
        except Exception:
            pass


def _email_to_model(msg, message_id: str) -> dict[str, Any]:
    subject = _decode_header(msg.get("subject", ""))
    from_address = msg.get("from", "")
    to_address = msg.get("to", "")
    cc = msg.get("cc", "")
    date = msg.get("date", "")
    headers = str(msg)[:20000]
    body = _extract_body(msg)
    snippet = body[:400]
    attachments = _extract_attachments(msg)
    attachments_summary = [
        f"{item['filename']}: {item['extracted_text'][:160] if item['extracted'] else '[unsupported or empty]'}"
        for item in attachments
    ]
    return {
        "message_id": message_id,
        "date": date,
        "from_address": from_address,
        "to_address": to_address,
        "cc": cc,
        "subject": subject,
        "snippet": snippet,
        "body": body[:15000],
        "raw_headers": headers,
        "attachments_summary": attachments_summary,
        "attachments": attachments,
    }


def _extract_body(msg) -> str:
    if msg.is_multipart():
        parts: list[str] = []
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            if content_type in {"text/plain", "text/html"}:
                payload = part.get_payload(decode=True) or b""
                parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
        return _normalize(" ".join(parts))
    payload = msg.get_payload(decode=True) or b""
    return _normalize(payload.decode(msg.get_content_charset() or "utf-8", errors="ignore"))


def _extract_attachments(msg) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if not msg.is_multipart():
        return output
    for part in msg.walk():
        disposition = (part.get("Content-Disposition") or "").lower()
        if "attachment" not in disposition:
            continue
        filename = part.get_filename() or "attachment"
        content_type = part.get_content_type() or "application/octet-stream"
        payload = part.get_payload(decode=True) or b""
        parsed_text = extract_attachment_text(filename, payload)
        output.append(
            {
                "filename": filename,
                "content_type": content_type,
                "extracted_text": parsed_text[:5000],
                "extracted": bool(parsed_text),
            }
        )
    return output


def _contains_target(msg, target: str) -> bool:
    if not target:
        return True
    headers = [
        msg.get("to", ""),
        msg.get("cc", ""),
        msg.get("delivered-to", ""),
        msg.get("x-original-to", ""),
        msg.get("x-forwarded-to", ""),
        msg.get("envelope-to", ""),
    ]
    addresses = [addr.lower() for _, addr in getaddresses(headers)]
    if any(addr == target for addr in addresses):
        return True
    return any(target in (h or "").lower() for h in headers)


def _decode_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _stdio_loop() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        req_id = req.get("id")
        method = req.get("method")
        try:
            if method == "tools/list":
                result = {"tools": list(TOOL_SCHEMAS.values())}
            elif method == "tools/call":
                params = req.get("params", {})
                name = params["name"]
                arguments = params.get("arguments", {})
                result = call_tool(name, arguments)
            else:
                raise ValueError(f"Unsupported method: {method}")
            resp = {"id": req_id, "result": result}
        except Exception as exc:
            resp = {"id": req_id, "error": {"message": str(exc)}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdio", action="store_true", help="Run line-based MCP stdio mode")
    parser.add_argument("--tool", type=str, default="", help="One-shot tool name")
    parser.add_argument("--args-json", type=str, default="{}", help="One-shot tool args JSON")
    args = parser.parse_args()

    if args.stdio:
        return _stdio_loop()
    if args.tool:
        payload = json.loads(args.args_json)
        result = call_tool(args.tool, payload)
        sys.stdout.write(json.dumps(result))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

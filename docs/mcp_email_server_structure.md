# MCP Email Server Minimal Structure

```text
searchtool/
  mcp_email_server/
    __init__.py
    server.py                # MCP tool entrypoint (stdio + one-shot)
    attachment_reader.py     # PDF/DOCX/CSV/XLSX extraction
  sold_item_finder/
    core/
      email/
        mcp_client.py        # Desktop app adapter calling MCP tools
        models.py
    ui/
      tabs/
        email_conn_tab.py    # Uses MCP client instead of direct IMAP connector
  docs/
    mcp_email_tools.json     # Exact tool schemas
    mcp_email_migration_checklist.md
```

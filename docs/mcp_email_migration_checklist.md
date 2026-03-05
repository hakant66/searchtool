# Email Conn to MCP Migration Checklist

- [x] Define MCP tool schemas (`email.test_connection`, `email.fetch_messages`)
- [x] Implement MCP server entrypoint (`mcp_email_server/server.py`)
- [x] Add attachment extraction for:
  - [x] `.pdf`
  - [x] `.docx`
  - [x] `.csv`
  - [x] `.xlsx`
- [x] Add app-side MCP client adapter (`core/email/mcp_client.py`)
- [x] Replace direct IMAP calls in `EmailConnTab` with MCP calls
- [x] Preserve existing keyring credential flow
- [x] Show subject/body/attachment extraction in email details pane
- [x] Keep debug screen logs with MCP fetch diagnostics
- [ ] Optional next step: switch one-shot MCP calls to persistent stdio session
- [ ] Optional next step: add OAuth2 Gmail API MCP backend

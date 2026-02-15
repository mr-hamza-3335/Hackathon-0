# AI Employee Email Server

MCP action server for email operations in the Personal AI Employee system.

## Tool: `send_email`

Compose and send professional emails. In Bronze mode, emails are saved as markdown drafts and sending is simulated via console output.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `to` | string | Yes | Recipient email address |
| `subject` | string | Yes | Email subject line |
| `body` | string | Yes | Email body (plain text or markdown) |
| `cc` | string | No | CC recipients (comma-separated) |
| `vault_path` | string | No | Path to vault root (default: `./vault`) |

### Response

```json
{
  "success": true,
  "message_id": "msg-2026-02-15T16-00-00-abc123",
  "file": "vault/drafts/2026-02-15T16-00-00_subject-slug.md",
  "status": "sent",
  "preview": "To: user@example.com | Subject: ... | Body preview..."
}
```

## Setup

```bash
cd mcp-servers/email-server
npm install
```

## Run

```bash
node server.js
```

The server communicates over stdio using the MCP protocol (JSON-RPC).

## Architecture

- **Bronze mode**: Saves draft to `vault/drafts/`, simulates send via console
- **Silver mode** (future): Connects to Gmail/SMTP API for real delivery

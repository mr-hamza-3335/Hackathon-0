---
title: Tools Registry
---

# Available MCP Tools

## demo-server

### draft_email

- **Description**: Drafts an email and saves it for review
- **Input**: `{ to, subject, body }`
- **Output**: `{ success, message_id, preview }`
- **Risk Tier**: T3 (External Write)
- **Approval**: Required

### create_file

- **Description**: Creates a file on the local filesystem
- **Input**: `{ path, content, overwrite }`
- **Output**: `{ success, path, size_bytes }`
- **Risk Tier**: T1 (Internal Write)
- **Approval**: Not required (Bronze: required)

## email-server

### send_email

- **Description**: Compose and send a professional email (simulated in Bronze)
- **Input**: `{ to, subject, body, cc? }`
- **Output**: `{ success, message_id, file, status, preview }`
- **Risk Tier**: T3 (External Write)
- **Approval**: Required

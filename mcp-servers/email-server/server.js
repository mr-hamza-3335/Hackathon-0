/**
 * AI Employee Email MCP Server
 *
 * A dedicated MCP server for email operations:
 *   - send_email: Draft and "send" an email (saves to vault, simulates sending)
 *
 * In Bronze mode, emails are saved as markdown drafts in vault/drafts/.
 * In Silver mode, this would connect to Gmail/SMTP APIs.
 *
 * Usage:
 *   node mcp-servers/email-server/server.js
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { writeFileSync, mkdirSync } from "fs";
import { join } from "path";

// Create the MCP server
const server = new McpServer({
  name: "ai-employee-email",
  version: "1.0.0",
});

// Register send_email tool
server.tool(
  "send_email",
  "Compose and send a professional email. In Bronze mode, the email is saved " +
    "as a markdown draft in vault/drafts/ and sending is simulated via console. " +
    "Returns a structured JSON result with message ID, file path, and status.",
  {
    to: z.string().describe("Recipient email address"),
    subject: z.string().describe("Email subject line"),
    body: z.string().describe("Email body content (plain text or markdown)"),
    cc: z.string().optional().describe("CC recipients (comma-separated)"),
    vault_path: z
      .string()
      .optional()
      .default("./vault")
      .describe("Path to vault root directory"),
  },
  async ({ to, subject, body, cc, vault_path }) => {
    // Validate required inputs
    if (!to || !subject || !body) {
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              success: false,
              error: "Missing required fields: to, subject, body",
            }),
          },
        ],
      };
    }

    const vaultRoot = vault_path || "./vault";
    const draftsDir = join(vaultRoot, "drafts");
    const now = new Date();
    const timestamp = now.toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const slug = subject
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .slice(0, 40);
    const messageId = `msg-${timestamp}-${Math.random().toString(36).slice(2, 8)}`;
    const filename = `${timestamp}_${slug}.md`;
    const filepath = join(draftsDir, filename);

    // Build the email draft as markdown
    const ccLine = cc ? `\n**CC:** ${cc}` : "";
    const content = `---
type: email-sent
message_id: "${messageId}"
to: "${to}"
subject: "${subject}"${cc ? `\ncc: "${cc}"` : ""}
created: "${now.toISOString()}"
status: sent
---

# Email

**To:** ${to}${ccLine}
**Subject:** ${subject}
**Date:** ${now.toISOString().slice(0, 10)}
**Message-ID:** ${messageId}

---

${body}

---
*Sent by AI Employee (Bronze Mode) — simulated delivery*
`;

    try {
      mkdirSync(draftsDir, { recursive: true });
      writeFileSync(filepath, content, "utf-8");

      // Simulate sending via console output
      console.error(`[EMAIL] Sending email...`);
      console.error(`[EMAIL]   To: ${to}`);
      if (cc) console.error(`[EMAIL]   CC: ${cc}`);
      console.error(`[EMAIL]   Subject: ${subject}`);
      console.error(`[EMAIL]   Body: ${body.slice(0, 100)}...`);
      console.error(`[EMAIL]   Status: SENT (simulated)`);
      console.error(`[EMAIL]   Message-ID: ${messageId}`);
      console.error(`[EMAIL]   Draft saved: ${filepath}`);

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              success: true,
              message_id: messageId,
              file: filepath,
              status: "sent",
              preview: `To: ${to} | Subject: ${subject} | ${body.slice(0, 80)}...`,
            }),
          },
        ],
      };
    } catch (err) {
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({
              success: false,
              error: `Failed to send email: ${err.message}`,
            }),
          },
        ],
      };
    }
  }
);

// Start the server on stdio
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("[MCP] ai-employee-email server running on stdio");
}

main().catch((err) => {
  console.error("[MCP] Fatal error:", err);
  process.exit(1);
});

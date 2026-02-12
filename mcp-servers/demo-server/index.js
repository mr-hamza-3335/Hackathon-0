/**
 * AI Employee Demo MCP Server — Bronze Tier
 *
 * A minimal MCP server that provides two tools:
 *   - draft_email: Save an email draft to the vault
 *   - create_file: Create a file on disk
 *
 * Communicates over stdio using the MCP protocol.
 *
 * Usage:
 *   node mcp-servers/demo-server/index.js
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import {
  definition as draftEmailDef,
  handler as draftEmailHandler,
} from "./tools/draft_email.js";
import {
  definition as createFileDef,
  handler as createFileHandler,
} from "./tools/create_file.js";

// Create the MCP server
const server = new McpServer({
  name: "ai-employee-demo",
  version: "1.0.0",
});

// Register draft_email tool
server.tool(
  draftEmailDef.name,
  draftEmailDef.description,
  {
    to: z.string().describe("Recipient email address"),
    subject: z.string().describe("Email subject line"),
    body: z.string().describe("Email body content"),
    vault_path: z
      .string()
      .optional()
      .default("./vault")
      .describe("Path to vault root"),
  },
  async (params) => {
    return await draftEmailHandler(params);
  }
);

// Register create_file tool
server.tool(
  createFileDef.name,
  createFileDef.description,
  {
    path: z.string().describe("File path to create"),
    content: z.string().describe("File content to write"),
    overwrite: z
      .boolean()
      .optional()
      .default(false)
      .describe("Overwrite existing files"),
  },
  async (params) => {
    return await createFileHandler(params);
  }
);

// Start the server on stdio
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("[MCP] ai-employee-demo server running on stdio");
}

main().catch((err) => {
  console.error("[MCP] Fatal error:", err);
  process.exit(1);
});

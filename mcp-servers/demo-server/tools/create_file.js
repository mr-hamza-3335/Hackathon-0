/**
 * create_file — Creates a file on the local filesystem.
 *
 * Used for generating reports, notes, or other documents
 * as part of task execution.
 */

import { writeFileSync, mkdirSync, existsSync } from "fs";
import { dirname } from "path";

export const definition = {
  name: "create_file",
  description:
    "Create a file with the specified content at the given path. " +
    "Will create parent directories if needed. " +
    "Will not overwrite existing files unless overwrite is true.",
  inputSchema: {
    type: "object",
    properties: {
      path: {
        type: "string",
        description: "File path (relative to project root or absolute)",
      },
      content: {
        type: "string",
        description: "File content to write",
      },
      overwrite: {
        type: "boolean",
        description: "Whether to overwrite existing files (default: false)",
        default: false,
      },
    },
    required: ["path", "content"],
  },
};

export async function handler({ path: filePath, content, overwrite }) {
  if (!filePath || content === undefined) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            success: false,
            error: "Missing required fields: path, content",
          }),
        },
      ],
    };
  }

  // Safety: prevent writing outside project
  if (filePath.includes("..")) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            success: false,
            error: "Path traversal not allowed (no .. in paths)",
          }),
        },
      ],
    };
  }

  if (!overwrite && existsSync(filePath)) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            success: false,
            error: `File already exists: ${filePath}. Set overwrite=true to replace.`,
          }),
        },
      ],
    };
  }

  try {
    mkdirSync(dirname(filePath), { recursive: true });
    writeFileSync(filePath, content, "utf-8");
    const sizeBytes = Buffer.byteLength(content, "utf-8");

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            success: true,
            path: filePath,
            size_bytes: sizeBytes,
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
            error: `Failed to create file: ${err.message}`,
          }),
        },
      ],
    };
  }
}

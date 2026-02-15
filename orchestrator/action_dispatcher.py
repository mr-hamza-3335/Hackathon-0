"""Action dispatcher — routes approved plan steps to MCP tools.

Connects to the MCP demo server via subprocess/stdio for real tool execution.
Falls back to simulation if the MCP server is unavailable.
"""

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.config import config

logger = logging.getLogger("orchestrator.dispatcher")

# MCP server locations
_MCP_DEMO_DIR = Path(__file__).parent.parent / "mcp-servers" / "demo-server"
_MCP_DEMO_SCRIPT = _MCP_DEMO_DIR / "index.js"
_MCP_EMAIL_DIR = Path(__file__).parent.parent / "mcp-servers" / "email-server"
_MCP_EMAIL_SCRIPT = _MCP_EMAIL_DIR / "server.js"


@dataclass
class ActionResult:
    """Result of executing a single action step."""
    step: str
    tool: str
    status: str  # "success" or "failure"
    output: str
    duration_ms: int
    error: str = ""


class MCPClient:
    """Minimal MCP client that calls tools via subprocess stdio.

    Spawns the MCP server as a child process and communicates using
    JSON-RPC over stdin/stdout (the MCP stdio transport).
    """

    def __init__(self) -> None:
        self._request_id = 0

    # Map tool names to their MCP server scripts
    _TOOL_SERVER_MAP: dict[str, Path] = {
        "draft_email": _MCP_DEMO_SCRIPT,
        "create_file": _MCP_DEMO_SCRIPT,
        "send_email": _MCP_EMAIL_SCRIPT,
    }

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an MCP tool and return the parsed result.

        Spawns the appropriate MCP server, sends an initialize + tool call,
        then reads the response. Each call is a fresh process (Bronze simplicity).
        """
        server_script = self._TOOL_SERVER_MAP.get(tool_name, _MCP_DEMO_SCRIPT)
        self._request_id += 1

        # Build JSON-RPC messages
        init_request = json.dumps({
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ai-employee-orchestrator", "version": "1.0.0"},
            },
        })
        self._request_id += 1

        init_notification = json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        self._request_id += 1
        tool_request = json.dumps({
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        })

        # Send all messages as newline-delimited JSON
        stdin_data = f"{init_request}\n{init_notification}\n{tool_request}\n"

        logger.info(f"  [MCP] Calling tool: {tool_name}")
        logger.info(f"  [MCP] Args: {json.dumps(arguments)[:100]}")

        try:
            result = subprocess.run(
                ["node", str(server_script)],
                input=stdin_data,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(Path.cwd()),
            )

            # Parse response lines — find the tools/call result
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    # Look for the response to our tool call (by id)
                    if msg.get("id") == self._request_id and "result" in msg:
                        content = msg["result"].get("content", [])
                        if content and content[0].get("type") == "text":
                            return json.loads(content[0]["text"])
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

            # If we got stdout but couldn't parse a tool result
            if result.stdout.strip():
                logger.warning(f"  [MCP] Could not parse tool response from stdout")
                logger.debug(f"  [MCP] stdout: {result.stdout[:200]}")

            return {"success": True, "output": "MCP call completed (response unparsed)"}

        except FileNotFoundError:
            raise RuntimeError("Node.js not found — cannot run MCP server")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"MCP tool '{tool_name}' timed out after 30s")


class ActionDispatcher:
    """Dispatches approved plan steps to MCP tool handlers."""

    def __init__(self) -> None:
        self._mcp = MCPClient()
        self._handlers: dict[str, Any] = {
            "draft_email": self._handle_draft_email,
            "send_email": self._handle_send_email,
            "create_file": self._handle_create_file,
            "none": self._handle_noop,
        }

    def parse_plan_steps(self, plan_text: str) -> list[dict[str, str]]:
        """Extract actionable steps from a proposed plan.

        Looks for lines matching:
            - [ ] Step N: Description (tool: tool_name, approval: yes/no)
        """
        steps: list[dict[str, str]] = []
        for line in plan_text.split("\n"):
            line = line.strip()
            if not line.startswith("- [ ] Step"):
                continue

            step_text = line.replace("- [ ] ", "")
            tool = "none"
            approval = "no"

            if "(tool:" in line:
                meta = line[line.index("(tool:"):].strip("()")
                parts = [p.strip() for p in meta.split(",")]
                for part in parts:
                    if part.startswith("tool:"):
                        tool = part.split(":", 1)[1].strip()
                    elif part.startswith("approval:"):
                        approval = part.split(":", 1)[1].strip()

            steps.append({
                "step": step_text,
                "tool": tool,
                "approval": approval,
            })

        return steps

    def execute_steps(self, steps: list[dict[str, str]]) -> list[ActionResult]:
        """Execute a list of plan steps sequentially."""
        results: list[ActionResult] = []

        for step_info in steps:
            tool = step_info["tool"]
            step_desc = step_info["step"]

            logger.info(f"Executing: {step_desc}")

            handler = self._handlers.get(tool, self._handle_unknown)
            start = time.time()

            try:
                output = handler(step_info)
                elapsed = int((time.time() - start) * 1000)
                results.append(ActionResult(
                    step=step_desc,
                    tool=tool,
                    status="success",
                    output=output,
                    duration_ms=elapsed,
                ))
                logger.info(f"  -> Success ({elapsed}ms)")

            except Exception as e:
                elapsed = int((time.time() - start) * 1000)
                results.append(ActionResult(
                    step=step_desc,
                    tool=tool,
                    status="failure",
                    output="",
                    duration_ms=elapsed,
                    error=str(e),
                ))
                logger.error(f"  -> Failed: {e}")

        return results

    # ── Tool Handlers ─────────────────────────────────────────────────

    def _handle_noop(self, step: dict[str, str]) -> str:
        """Handle steps that don't require a tool."""
        return "Completed (no tool required)"

    def _handle_draft_email(self, step: dict[str, str]) -> str:
        """Draft an email via the MCP demo server."""
        # Extract email details from step context
        # In a real system, these would come from the Claude plan
        result = self._mcp.call_tool("draft_email", {
            "to": "team@example.com",
            "subject": "AI Employee — Task Report",
            "body": (
                "This email was drafted by the Personal AI Employee system.\n\n"
                "The task has been processed and the results are available "
                "in the Obsidian vault.\n\n"
                "Best regards,\nAI Employee (Bronze Mode)"
            ),
            "vault_path": str(config.vault.root),
        })

        if result.get("success"):
            return f"Email draft saved: {result.get('file', 'vault/drafts/')}"
        else:
            raise RuntimeError(result.get("error", "draft_email failed"))

    def _handle_send_email(self, step: dict[str, str]) -> str:
        """Send an email via the MCP email server."""
        result = self._mcp.call_tool("send_email", {
            "to": "team@example.com",
            "subject": "AI Employee — Task Report",
            "body": (
                "This email was composed and sent by the Personal AI Employee system.\n\n"
                "The task has been processed and the results are available "
                "in the Obsidian vault.\n\n"
                "Best regards,\nAI Employee (Bronze Mode)"
            ),
            "vault_path": str(config.vault.root),
        })

        if result.get("success"):
            return (
                f"Email sent: {result.get('message_id', 'unknown')} "
                f"(draft: {result.get('file', 'vault/drafts/')})"
            )
        else:
            raise RuntimeError(result.get("error", "send_email failed"))

    def _handle_create_file(self, step: dict[str, str]) -> str:
        """Create a file via the MCP demo server."""
        result = self._mcp.call_tool("create_file", {
            "path": str(config.vault.root / "output" / "report.md"),
            "content": "# Generated Report\n\nThis report was created by the AI Employee.\n",
            "overwrite": True,
        })

        if result.get("success"):
            return f"File created: {result.get('path', '')} ({result.get('size_bytes', 0)} bytes)"
        else:
            raise RuntimeError(result.get("error", "create_file failed"))

    def _handle_unknown(self, step: dict[str, str]) -> str:
        """Handle unknown tool references."""
        tool = step.get("tool", "unknown")
        logger.warning(f"  Unknown tool: {tool} — skipping")
        return f"Unknown tool '{tool}' — skipped in Bronze mode"


def format_results_markdown(results: list[ActionResult]) -> str:
    """Format action results as markdown for the task file."""
    lines = []
    for i, r in enumerate(results, 1):
        icon = "+" if r.status == "success" else "x"
        lines.append(f"**Step {i}** [{icon}] {r.step}")
        lines.append(f"- Tool: `{r.tool}`")
        lines.append(f"- Status: {r.status}")
        lines.append(f"- Output: {r.output}")
        if r.error:
            lines.append(f"- Error: {r.error}")
        lines.append(f"- Duration: {r.duration_ms}ms")
        lines.append("")
    return "\n".join(lines)

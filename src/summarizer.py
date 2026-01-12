"""
LLM-based summarizer using Claude Agent SDK.

THE SUMMARIES ARE THE PRODUCT. If they're not crisp, clear, and impressive,
nobody will use Tower. Every summary should make the user think "wow, this
actually understands what's happening and tells me exactly what I need to know."

Uses Claude Agent SDK with custom tools for context gathering:
- git_status: See what files have changed
- git_diff: See actual changes
- git_log: Recent commit history
- read_file: Look at specific files
"""

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass
from typing import Optional, Any

from event_detector import DetectedEvent, EventType

# Try to import Agent SDK, fall back to basic Anthropic if not available
try:
    from claude_agent_sdk import (
        query,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        tool,
        create_sdk_mcp_server,
    )
    AGENT_SDK_AVAILABLE = True
except ImportError:
    AGENT_SDK_AVAILABLE = False
    from anthropic import Anthropic


@dataclass
class SummaryOption:
    key: str  # DTMF key (1, 2, 3, etc.)
    label: str  # Short label for the option
    instruction: str  # What to send back to Claude Code


@dataclass
class Summary:
    speech_text: str
    options: list[SummaryOption]
    context_snippet: str


# Tools for context gathering
def run_git_command(args: list[str], cwd: Optional[str] = None) -> str:
    """Run a git command and return output."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd or os.getcwd(),
        )
        return result.stdout[:2000] if result.stdout else result.stderr[:500]
    except Exception as e:
        return f"Error: {e}"


def read_file_content(path: str, max_lines: int = 50) -> str:
    """Read a file's content."""
    try:
        with open(path, 'r') as f:
            lines = f.readlines()[:max_lines]
            return ''.join(lines)
    except Exception as e:
        return f"Error reading {path}: {e}"


# Tool definitions for Agent SDK
if AGENT_SDK_AVAILABLE:
    @tool("git_status", "Get git status showing changed files", {})
    async def git_status_tool(args: dict[str, Any]) -> dict[str, Any]:
        output = run_git_command(["status", "--short"])
        return {"content": [{"type": "text", "text": output}]}

    @tool("git_diff", "Get git diff showing actual changes", {"file": str})
    async def git_diff_tool(args: dict[str, Any]) -> dict[str, Any]:
        file_arg = args.get("file", "")
        cmd = ["diff", "--stat"] if not file_arg else ["diff", file_arg]
        output = run_git_command(cmd)
        return {"content": [{"type": "text", "text": output}]}

    @tool("git_log", "Get recent git commits", {"count": int})
    async def git_log_tool(args: dict[str, Any]) -> dict[str, Any]:
        count = min(args.get("count", 5), 10)
        output = run_git_command(["log", f"-{count}", "--oneline"])
        return {"content": [{"type": "text", "text": output}]}

    @tool("read_file", "Read a file's contents", {"path": str})
    async def read_file_tool(args: dict[str, Any]) -> dict[str, Any]:
        path = args.get("path", "")
        if not path:
            return {"content": [{"type": "text", "text": "Error: path required"}], "is_error": True}
        content = read_file_content(path)
        return {"content": [{"type": "text", "text": content}]}


SYSTEM_PROMPT = """You are Tower, an elite AI ops assistant. A developer is monitoring their AI coding agents remotely. They need YOU to translate messy terminal output into crystal-clear, actionable intelligence.

YOUR SUMMARIES MUST BE IMPRESSIVE. This is how Tower gets adopted. If your summaries are vague or generic, the developer will just check the terminal themselves. You need to prove you actually understand what's happening.

RULES FOR IMPRESSIVE SUMMARIES:
1. BE SPECIFIC - Don't say "there's an error". Say "3 auth tests failed - login returns 401 instead of 200, likely a token issue"
2. SHOW INSIGHT - Identify the root cause when possible, not just symptoms
3. BE ACTIONABLE - Every option should be a clear next step, not generic "continue/stop"
4. NO JARGON WALLS - Translate technical output into clear English, but keep technical accuracy
5. BE CONFIDENT - You're an expert assistant, not a hesitant helper
6. CONTEXT MATTERS - Reference the specific file, function, or feature being worked on

You have tools to gather additional context:
- git_status: See what files changed
- git_diff: See the actual code changes
- git_log: See recent commits
- read_file: Look at specific files mentioned in errors

Use these tools when the terminal output references files or you need more context to understand the root cause.

GOOD EXAMPLE:
"Auth tests are failing. The login endpoint returns 401 - looks like the JWT secret changed but the test fixtures weren't updated. The signup and password reset tests are also down because they depend on login."

BAD EXAMPLE:
"Some tests failed. There were errors in the authentication module."

Respond with JSON only:
{
  "speech": "Your impressive, specific, actionable summary (2-3 sentences max)",
  "options": [
    { "key": "1", "label": "specific action", "instruction": "exact instruction to send to Claude Code" },
    { "key": "2", "label": "specific action", "instruction": "exact instruction to send to Claude Code" }
  ]
}"""


class Summarizer:
    """Converts events into speakable summaries with options.

    Uses Claude Agent SDK with your existing Claude Code login - no API key needed.
    Falls back to basic Anthropic client only if SDK unavailable AND API key provided.
    """

    def __init__(self):
        self.use_agent_sdk = AGENT_SDK_AVAILABLE
        self.client = None

        if not self.use_agent_sdk:
            # Fallback only if SDK not available - requires API key
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if api_key:
                self.client = Anthropic(api_key=api_key)
            else:
                print("[Tower] Warning: Agent SDK not available and no ANTHROPIC_API_KEY set")
                print("[Tower] Install claude-agent-sdk or set ANTHROPIC_API_KEY for summaries")

    def summarize(self, event: DetectedEvent) -> Summary:
        """Generate a spoken summary and options for an event."""
        if self.use_agent_sdk:
            return asyncio.run(self._summarize_with_agent_sdk(event))
        elif self.client:
            return self._summarize_with_anthropic(event)
        else:
            # No LLM available - return basic summary from event data
            return self._basic_summary(event)

    def _basic_summary(self, event: DetectedEvent) -> Summary:
        """Fallback summary when no LLM is available."""
        type_messages = {
            EventType.ERROR: "Error detected in Claude Code session.",
            EventType.PERMISSION: "Claude Code is waiting for permission.",
            EventType.STUCK: "Claude Code session appears stuck.",
            EventType.NORMAL: "Claude Code session update.",
        }
        return Summary(
            speech_text=type_messages.get(event.event_type, "Claude Code needs attention."),
            options=[
                SummaryOption("1", "approve", "yes"),
                SummaryOption("2", "retry", "retry"),
                SummaryOption("9", "stop", "Stop and wait for me"),
            ],
            context_snippet="\n".join(event.key_lines),
        )

    async def _summarize_with_agent_sdk(self, event: DetectedEvent) -> Summary:
        """Use Claude Agent SDK with tools for better summaries."""
        # Create MCP server with context tools
        context_server = create_sdk_mcp_server(
            name="tower-context",
            version="1.0.0",
            tools=[git_status_tool, git_diff_tool, git_log_tool, read_file_tool]
        )

        prompt = f"""Analyze this terminal output and provide a summary.

Event type: {event.event_type.value}

Key lines:
{chr(10).join(f"- {line}" for line in event.key_lines)}

Full recent output:
---
{event.raw_output[-2000:]}
---

Use the context tools if you need more information about git changes or file contents.
Then respond with JSON only (speech and options)."""

        options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={"ctx": context_server},
            allowed_tools=[
                "mcp__ctx__git_status",
                "mcp__ctx__git_diff",
                "mcp__ctx__git_log",
                "mcp__ctx__read_file"
            ],
            max_turns=3,
            max_budget_usd=0.05,  # Cap cost per summary
        )

        response_text = ""
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_text += block.text

        return self._parse_response(response_text, event)

    def _summarize_with_anthropic(self, event: DetectedEvent) -> Summary:
        """Fallback to basic Anthropic API."""
        prompt = f"""Analyze this terminal output and provide a summary.

Event type: {event.event_type.value}

Key lines:
{chr(10).join(f"- {line}" for line in event.key_lines)}

Full recent output:
---
{event.raw_output[-2000:]}
---

Respond with JSON only (speech and options)."""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        return self._parse_response(response.content[0].text, event)

    def _parse_response(self, text: str, event: DetectedEvent) -> Summary:
        """Parse LLM response into Summary object."""
        data = self._extract_json(text)

        if data is None:
            print(f"[Tower] Failed to parse LLM response: {text[:200]}")
            return Summary(
                speech_text="Claude Code needs your attention but I couldn't parse the details.",
                options=[
                    SummaryOption("1", "continue", "Continue with the current task"),
                    SummaryOption("2", "stop", "Stop and wait for me"),
                ],
                context_snippet=event.raw_output[-500:],
            )

        # Validate and build options
        options = []
        for opt in data.get("options", []):
            key = str(opt.get("key", ""))
            label = str(opt.get("label", ""))
            instruction = str(opt.get("instruction", ""))

            # Validate key is a single digit
            if not key.isdigit() or len(key) != 1:
                continue

            # Skip if missing required fields
            if not label or not instruction:
                continue

            options.append(SummaryOption(key=key, label=label, instruction=instruction))

        # Always add a "stop" option if not present
        if not any(opt.key == "9" for opt in options):
            options.append(
                SummaryOption("9", "stop everything", "Stop immediately and wait for me")
            )

        return Summary(
            speech_text=data.get("speech", "Claude Code needs attention."),
            options=options,
            context_snippet="\n".join(event.key_lines),
        )

    def _extract_json(self, text: str) -> Optional[dict]:
        """Extract JSON from LLM response, handling common formatting issues."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strip markdown code blocks
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # Try again after stripping
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Find first { and last } and try to extract
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        return None


if __name__ == "__main__":
    # Test with mock event
    from dotenv import load_dotenv

    load_dotenv()

    mock_event = DetectedEvent(
        event_type=EventType.ERROR,
        raw_output="""
Running tests...
FAILED tests/test_auth.py::test_login_flow - AssertionError: Expected 200, got 401
FAILED tests/test_auth.py::test_signup - ConnectionError: Database unavailable
FAILED tests/test_auth.py::test_password_reset - TimeoutError

3 failed, 12 passed in 4.32s
        """,
        key_lines=[
            "FAILED tests/test_auth.py::test_login_flow - AssertionError: Expected 200, got 401",
            "FAILED tests/test_auth.py::test_signup - ConnectionError: Database unavailable",
            "3 failed, 12 passed in 4.32s",
        ],
        confidence=0.9,
        timestamp=0,
    )

    summarizer = Summarizer()
    summary = summarizer.summarize(mock_event)

    print(f"Speech: {summary.speech_text}")
    print(f"\nOptions:")
    for opt in summary.options:
        print(f"  {opt.key}: {opt.label} -> {opt.instruction}")

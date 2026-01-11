"""
LLM-based summarizer that converts raw tmux output into speakable summaries.
"""

import json
import os
from dataclasses import dataclass
from typing import Optional

from anthropic import Anthropic

from event_detector import DetectedEvent, EventType


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


SUMMARIZE_PROMPT = """You are a voice assistant helping a developer monitor their AI coding agent.

Given this terminal output from Claude Code, create a brief phone message:
1. What happened (1-2 sentences, no jargon, speakable)
2. What are the options (2-3 choices max)
3. For each option, what instruction to send back to the agent

The developer will hear this over the phone and respond by pressing a number key.

Event type detected: {event_type}
Key lines identified:
{key_lines}

Full recent output:
---
{raw_output}
---

Respond with JSON only, no markdown:
{{
  "speech": "Brief spoken summary of what happened",
  "options": [
    {{ "key": "1", "label": "short label", "instruction": "full instruction to send to Claude" }},
    {{ "key": "2", "label": "short label", "instruction": "full instruction to send to Claude" }}
  ]
}}"""


class Summarizer:
    """Converts events into speakable summaries with options."""

    def __init__(self, api_key: Optional[str] = None):
        self.client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    def summarize(self, event: DetectedEvent) -> Summary:
        """Generate a spoken summary and options for an event."""
        prompt = SUMMARIZE_PROMPT.format(
            event_type=event.event_type.value,
            key_lines="\n".join(f"- {line}" for line in event.key_lines),
            raw_output=event.raw_output[-2000:],  # Limit context
        )

        response = self.client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse JSON response
        text = response.content[0].text
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Fallback for malformed response
            return Summary(
                speech_text="Claude Code needs your attention but I couldn't parse the details.",
                options=[
                    SummaryOption("1", "continue", "Continue with the current task"),
                    SummaryOption("2", "stop", "Stop and wait for me"),
                ],
                context_snippet=event.raw_output[-500:],
            )

        options = [
            SummaryOption(
                key=opt["key"],
                label=opt["label"],
                instruction=opt["instruction"],
            )
            for opt in data.get("options", [])
        ]

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

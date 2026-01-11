"""
Event detection from tmux pane output.
Monitors Claude Code sessions for errors, permission prompts, and stalls.
"""

import re
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class EventType(Enum):
    ERROR = "error"
    PERMISSION = "permission"
    STUCK = "stuck"
    NORMAL = "normal"


@dataclass
class DetectedEvent:
    event_type: EventType
    raw_output: str
    key_lines: list[str]
    confidence: float
    timestamp: float


# Pattern matching for common Claude Code events
ERROR_PATTERNS = [
    r"FAILED",
    r"Error:",
    r"Traceback \(most recent call last\)",
    r"error\[E\d+\]",  # Rust errors
    r"npm ERR!",
    r"exit code [1-9]",
    r"Command failed",
]

PERMISSION_PATTERNS = [
    r"Do you want to",
    r"Allow\?",
    r"Proceed\?",
    r"Continue\?",
    r"Are you sure",
    r"\[y/N\]",
    r"\[Y/n\]",
]


def capture_tmux_pane(pane_id: str, lines: int = 50) -> str:
    """Capture the last N lines from a tmux pane."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-S", f"-{lines}", "-t", pane_id],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return strip_ansi(result.stdout)
    except subprocess.TimeoutExpired:
        return ""
    except subprocess.CalledProcessError:
        return ""


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_pattern.sub("", text)


def detect_event(output: str) -> DetectedEvent:
    """Analyze tmux output and classify the current state."""
    lines = output.strip().split("\n")
    key_lines = []

    # Check for errors
    for pattern in ERROR_PATTERNS:
        for line in lines:
            if re.search(pattern, line, re.IGNORECASE):
                key_lines.append(line.strip())
                if len(key_lines) >= 5:
                    break
        if key_lines:
            return DetectedEvent(
                event_type=EventType.ERROR,
                raw_output=output,
                key_lines=key_lines[:5],
                confidence=0.9,
                timestamp=time.time(),
            )

    # Check for permission prompts
    for pattern in PERMISSION_PATTERNS:
        for line in lines[-10:]:  # Permission prompts are usually recent
            if re.search(pattern, line, re.IGNORECASE):
                key_lines.append(line.strip())
                return DetectedEvent(
                    event_type=EventType.PERMISSION,
                    raw_output=output,
                    key_lines=key_lines[:3],
                    confidence=0.95,
                    timestamp=time.time(),
                )

    # Normal state
    return DetectedEvent(
        event_type=EventType.NORMAL,
        raw_output=output,
        key_lines=[],
        confidence=1.0,
        timestamp=time.time(),
    )


class TmuxMonitor:
    """Monitors a tmux pane for events that need escalation."""

    def __init__(self, pane_id: str, poll_interval: float = 2.0):
        self.pane_id = pane_id
        self.poll_interval = poll_interval
        self.last_output = ""
        self.last_event_time = 0
        self.debounce_seconds = 300  # 5 minutes

    def check_once(self) -> Optional[DetectedEvent]:
        """Check for new events. Returns event if one is detected."""
        output = capture_tmux_pane(self.pane_id)

        # Skip if output hasn't changed
        if output == self.last_output:
            return None

        self.last_output = output
        event = detect_event(output)

        # Skip normal events
        if event.event_type == EventType.NORMAL:
            return None

        # Debounce: don't re-trigger too quickly
        if time.time() - self.last_event_time < self.debounce_seconds:
            return None

        self.last_event_time = time.time()
        return event

    def run(self, callback):
        """Run the monitor loop, calling callback on each detected event."""
        print(f"Monitoring tmux pane {self.pane_id}...")
        while True:
            event = self.check_once()
            if event:
                callback(event)
            time.sleep(self.poll_interval)


if __name__ == "__main__":
    # Quick test
    import os
    from dotenv import load_dotenv

    load_dotenv()
    pane = os.getenv("TMUX_TARGET_PANE", "%0")

    def on_event(event: DetectedEvent):
        print(f"\n{'='*50}")
        print(f"EVENT: {event.event_type.value}")
        print(f"Confidence: {event.confidence}")
        print(f"Key lines:")
        for line in event.key_lines:
            print(f"  > {line}")
        print(f"{'='*50}\n")

    monitor = TmuxMonitor(pane)
    monitor.run(on_event)

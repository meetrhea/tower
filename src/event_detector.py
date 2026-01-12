"""
Event detection from tmux pane output and Claude Code hooks.

Two detection modes:
1. Hooks (instant) - Claude Code calls our hook script on permission prompts
2. Tmux polling (fallback) - Monitors for errors, STUCK state, and sessions without hooks

The hooks integration provides instant notifications instead of 2-second polling delay.
"""

import asyncio
import json
import os
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


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

# Patterns indicating agent might be stuck (no progress)
STUCK_INDICATORS = [
    r"Waiting for.*response",
    r"Connection timed out",
    r"Rate limit exceeded",
    r"Request failed",
    r"retrying",
]

# Default socket path for hooks communication
DEFAULT_SOCKET_PATH = "/tmp/tower.sock"


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
        self.last_change_time = time.time()
        self.debounce_seconds = 300  # 5 minutes
        self.stuck_threshold = 600  # 10 minutes without change = stuck

    def check_once(self) -> Optional[DetectedEvent]:
        """Check for new events. Returns event if one is detected."""
        output = capture_tmux_pane(self.pane_id)

        # Track output changes for STUCK detection
        if output != self.last_output:
            self.last_change_time = time.time()
            self.last_output = output
        else:
            # Check for STUCK state: no output change for threshold
            idle_time = time.time() - self.last_change_time
            if idle_time > self.stuck_threshold:
                # Only trigger STUCK once per threshold period
                if time.time() - self.last_event_time > self.debounce_seconds:
                    self.last_event_time = time.time()
                    return DetectedEvent(
                        event_type=EventType.STUCK,
                        raw_output=output,
                        key_lines=[f"No activity for {int(idle_time / 60)} minutes"],
                        confidence=0.8,
                        timestamp=time.time(),
                    )
            return None

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
        print(f"[Tower] Monitoring tmux pane {self.pane_id}...")
        while True:
            event = self.check_once()
            if event:
                callback(event)
            time.sleep(self.poll_interval)


class HooksListener:
    """
    Listens for events from Claude Code hooks via Unix socket.

    This provides instant notification when Claude Code hits a permission prompt,
    instead of waiting for the 2-second tmux polling interval.

    Usage:
        listener = HooksListener(callback=my_handler)
        await listener.start()  # Runs until cancelled
    """

    def __init__(
        self,
        callback: Callable[[DetectedEvent], None],
        socket_path: str = DEFAULT_SOCKET_PATH,
    ):
        self.callback = callback
        self.socket_path = socket_path
        self.server = None
        self._running = False

    async def start(self):
        """Start listening for hook events."""
        # Remove stale socket file
        socket_file = Path(self.socket_path)
        if socket_file.exists():
            socket_file.unlink()

        # Create Unix socket server
        self.server = await asyncio.start_unix_server(
            self._handle_connection, self.socket_path
        )

        # Make socket world-writable so hooks can connect
        os.chmod(self.socket_path, 0o666)

        self._running = True
        print(f"[Tower] Hooks listener started on {self.socket_path}")

        async with self.server:
            await self.server.serve_forever()

    async def stop(self):
        """Stop the listener."""
        self._running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()

        # Clean up socket file
        socket_file = Path(self.socket_path)
        if socket_file.exists():
            socket_file.unlink()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handle incoming hook event."""
        try:
            data = await asyncio.wait_for(reader.read(8192), timeout=5.0)
            if not data:
                return

            # Parse the hook event
            try:
                hook_data = json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                print(f"[Tower] Invalid JSON from hook: {data[:100]}")
                return

            # Convert to DetectedEvent
            event = self._parse_hook_event(hook_data)
            if event:
                # Call the callback (run in executor if it's sync)
                if asyncio.iscoroutinefunction(self.callback):
                    await self.callback(event)
                else:
                    self.callback(event)

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            print(f"[Tower] Hook handler error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    def _parse_hook_event(self, hook_data: dict) -> Optional[DetectedEvent]:
        """Convert hook JSON data to DetectedEvent."""
        event_name = hook_data.get("hook_event_name", "")

        # Extract key information based on event type
        key_lines = []
        raw_output = json.dumps(hook_data, indent=2)

        if event_name == "PermissionRequest":
            # Permission prompt detected
            tool_name = hook_data.get("tool_name", "unknown")
            tool_input = hook_data.get("tool_input", {})

            key_lines.append(f"Permission requested for: {tool_name}")
            if isinstance(tool_input, dict):
                # Add relevant details based on tool
                if "command" in tool_input:
                    key_lines.append(f"Command: {tool_input['command'][:100]}")
                if "file_path" in tool_input:
                    key_lines.append(f"File: {tool_input['file_path']}")

            return DetectedEvent(
                event_type=EventType.PERMISSION,
                raw_output=raw_output,
                key_lines=key_lines,
                confidence=1.0,  # High confidence - direct from Claude Code
                timestamp=time.time(),
            )

        elif event_name == "Notification":
            # Could be permission_prompt or other notification
            notification_type = hook_data.get("notification_type", "")
            if notification_type == "permission_prompt":
                key_lines.append("Permission prompt notification")
                return DetectedEvent(
                    event_type=EventType.PERMISSION,
                    raw_output=raw_output,
                    key_lines=key_lines,
                    confidence=1.0,
                    timestamp=time.time(),
                )

        # Unknown or unhandled event type
        return None


if __name__ == "__main__":
    # Quick test - can run with --hooks to test hooks listener
    import sys
    from dotenv import load_dotenv

    load_dotenv()

    def on_event(event: DetectedEvent):
        print(f"\n{'='*50}")
        print(f"EVENT: {event.event_type.value}")
        print(f"Confidence: {event.confidence}")
        print(f"Key lines:")
        for line in event.key_lines:
            print(f"  > {line}")
        print(f"{'='*50}\n")

    if "--hooks" in sys.argv:
        # Test hooks listener
        print("Testing hooks listener...")
        print("Send events to the socket with:")
        print('  echo \'{"hook_event_name":"PermissionRequest","tool_name":"Bash"}\' | nc -U /tmp/tower.sock')

        async def run_hooks():
            listener = HooksListener(callback=on_event)
            await listener.start()

        asyncio.run(run_hooks())
    else:
        # Test tmux monitor
        pane = os.getenv("TMUX_TARGET_PANE", "%0")
        print(f"Testing tmux monitor on pane {pane}...")
        monitor = TmuxMonitor(pane)
        monitor.run(on_event)

"""
Main entry point for the Claude Code phone wrapper.
Orchestrates event detection, summarization, calling, and response handling.
"""

import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

from event_detector import DetectedEvent, EventType, TmuxMonitor
from summarizer import Summary, Summarizer
from phone_caller import PhoneCaller, LocalTTSFallback


@dataclass
class InteractionLog:
    """Log entry for each escalation interaction."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    session: str = ""
    pane: str = ""
    event_type: str = ""
    raw_output: str = ""
    speech_text: str = ""
    options_offered: list = field(default_factory=list)
    human_response: str = ""
    instruction_sent: str = ""
    outcome: str = ""


class ClaudeCodeWrapper:
    """Main wrapper that ties everything together."""

    def __init__(
        self,
        pane_id: str,
        phone_number: Optional[str] = None,
        use_phone: bool = False,
    ):
        self.pane_id = pane_id
        self.phone_number = phone_number or os.getenv("PHONE_TO")
        self.use_phone = use_phone

        self.monitor = TmuxMonitor(pane_id)
        self.summarizer = Summarizer()

        if use_phone:
            self.caller = PhoneCaller()
        else:
            self.caller = LocalTTSFallback()

        self.logs: list[InteractionLog] = []

    def send_to_claude(self, instruction: str) -> bool:
        """Send an instruction back to the Claude Code pane."""
        try:
            # Send the instruction text
            subprocess.run(
                ["tmux", "send-keys", "-t", self.pane_id, instruction, "Enter"],
                check=True,
                timeout=5,
            )
            print(f"[Sent] {instruction}")
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"[Error] Failed to send to tmux: {e}")
            return False

    def handle_event(self, event: DetectedEvent):
        """Process a detected event through the full pipeline."""
        print(f"\n{'='*60}")
        print(f"EVENT DETECTED: {event.event_type.value}")
        print(f"Time: {datetime.now().isoformat()}")
        print(f"{'='*60}")

        # Create log entry
        log = InteractionLog(
            pane=self.pane_id,
            event_type=event.event_type.value,
            raw_output=event.raw_output[-1000:],
        )

        # Generate summary
        print("\nGenerating summary...")
        summary = self.summarizer.summarize(event)
        log.speech_text = summary.speech_text
        log.options_offered = [
            {"key": o.key, "label": o.label} for o in summary.options
        ]

        print(f"\nSummary: {summary.speech_text}")

        # Get human response
        if self.use_phone:
            print(f"\nCalling {self.phone_number}...")
            session_id = log.id
            result = self.caller.make_call(self.phone_number, summary, session_id)
            print(f"Call initiated: {result.call_sid}")
            # Note: In real implementation, we'd wait for webhook callback
            # For now, fall back to local input
            response = input("Enter response digit (simulating phone): ").strip()
        else:
            response = self.caller.speak_and_prompt(summary)

        log.human_response = response or ""

        # Map response to instruction
        instruction = None
        for opt in summary.options:
            if opt.key == response:
                instruction = opt.instruction
                break

        if instruction:
            log.instruction_sent = instruction
            success = self.send_to_claude(instruction)
            log.outcome = "sent" if success else "send_failed"
        else:
            print(f"No matching option for response: {response}")
            log.outcome = "no_match"

        self.logs.append(log)
        self._save_log(log)

        print(f"\n{'='*60}\n")

    def _save_log(self, log: InteractionLog):
        """Save log entry to file (SQLite in production)."""
        import json

        log_file = os.path.join(
            os.path.dirname(__file__), "..", "logs", "interactions.jsonl"
        )
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        with open(log_file, "a") as f:
            f.write(json.dumps(log.__dict__) + "\n")

    def run(self):
        """Start the monitoring loop."""
        print(f"\nClaude Code Phone Wrapper")
        print(f"{'='*40}")
        print(f"Monitoring pane: {self.pane_id}")
        print(f"Phone mode: {'enabled' if self.use_phone else 'disabled (local TTS)'}")
        if self.use_phone:
            print(f"Phone number: {self.phone_number}")
        print(f"{'='*40}\n")
        print("Press Ctrl+C to stop.\n")

        try:
            self.monitor.run(self.handle_event)
        except KeyboardInterrupt:
            print("\nStopping wrapper...")
            print(f"Logged {len(self.logs)} interactions.")


def main():
    load_dotenv()

    import argparse

    parser = argparse.ArgumentParser(description="Claude Code Phone Wrapper")
    parser.add_argument(
        "--pane",
        default=os.getenv("TMUX_TARGET_PANE", "%0"),
        help="tmux pane ID to monitor (default: %%0)",
    )
    parser.add_argument(
        "--phone",
        action="store_true",
        help="Enable phone calls instead of local TTS",
    )
    parser.add_argument(
        "--number",
        default=os.getenv("PHONE_TO"),
        help="Phone number to call",
    )

    args = parser.parse_args()

    wrapper = ClaudeCodeWrapper(
        pane_id=args.pane,
        phone_number=args.number,
        use_phone=args.phone,
    )

    wrapper.run()


if __name__ == "__main__":
    main()

"""
Twilio integration for making outbound calls with dynamic TwiML.
"""

import os
from dataclasses import dataclass
from typing import Optional

from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather

from summarizer import Summary


@dataclass
class CallResult:
    call_sid: str
    status: str
    response_digit: Optional[str] = None
    response_audio_url: Optional[str] = None


class PhoneCaller:
    """Handles outbound calls via Twilio."""

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
        webhook_base_url: Optional[str] = None,
    ):
        self.account_sid = account_sid or os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = from_number or os.getenv("TWILIO_PHONE_FROM")
        self.webhook_base_url = webhook_base_url or os.getenv("WEBHOOK_BASE_URL")

        self.client = Client(self.account_sid, self.auth_token)

    def generate_twiml(self, summary: Summary, session_id: str) -> str:
        """Generate TwiML for the call based on the summary."""
        response = VoiceResponse()

        # Speak the summary
        response.say(summary.speech_text, voice="alice")

        # Build options speech
        options_text = " ".join(
            f"Press {opt.key} to {opt.label}." for opt in summary.options
        )

        # Gather DTMF input
        gather = Gather(
            num_digits=1,
            action=f"{self.webhook_base_url}/webhook/response?session={session_id}",
            method="POST",
            timeout=30,
        )
        gather.say(options_text, voice="alice")
        response.append(gather)

        # Fallback if no input
        response.say("No input received. The agent will continue waiting.", voice="alice")
        response.hangup()

        return str(response)

    def make_call(self, to_number: str, summary: Summary, session_id: str) -> CallResult:
        """Initiate an outbound call with the summary."""
        # For demo, we use a TwiML Bin or webhook URL
        # In production, you'd host the TwiML endpoint
        twiml = self.generate_twiml(summary, session_id)

        call = self.client.calls.create(
            to=to_number,
            from_=self.from_number,
            twiml=twiml,
        )

        return CallResult(
            call_sid=call.sid,
            status=call.status,
        )


class LocalTTSFallback:
    """Local TTS for development without Twilio."""

    def __init__(self):
        try:
            import pyttsx3
            self.engine = pyttsx3.init()
            self.engine.setProperty("rate", 180)
        except Exception:
            self.engine = None

    def speak_and_prompt(self, summary: Summary) -> Optional[str]:
        """Speak the summary and wait for keyboard input."""
        if not self.engine:
            print(f"\n[TTS] {summary.speech_text}")
        else:
            self.engine.say(summary.speech_text)
            self.engine.runAndWait()

        # Print options
        print("\nOptions:")
        for opt in summary.options:
            print(f"  {opt.key}: {opt.label}")

        # Get keyboard input
        try:
            choice = input("\nPress a number and Enter: ").strip()
            return choice if choice else None
        except (EOFError, KeyboardInterrupt):
            return None


if __name__ == "__main__":
    from dotenv import load_dotenv
    from summarizer import SummaryOption

    load_dotenv()

    # Test with mock summary
    mock_summary = Summary(
        speech_text="Your tests failed in the auth module. Three tests are broken.",
        options=[
            SummaryOption("1", "retry tests", "Run the tests again"),
            SummaryOption("2", "skip and continue", "Skip failing tests and continue"),
            SummaryOption("9", "stop", "Stop and wait for me"),
        ],
        context_snippet="3 failed, 12 passed",
    )

    # Test local TTS
    local = LocalTTSFallback()
    choice = local.speak_and_prompt(mock_summary)
    print(f"\nYou chose: {choice}")

    # Find matching option
    for opt in mock_summary.options:
        if opt.key == choice:
            print(f"Instruction to send: {opt.instruction}")
            break

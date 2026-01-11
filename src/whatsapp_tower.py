"""
Tower via WhatsApp - Text-first interface for AI agent control.

MVP flow:
1. Tower monitors tmux sessions for events
2. Sends WhatsApp message when agent needs attention
3. You reply via text (or voice message, transcribed later)
4. Tower sends instruction back to the agent

Later: voice message transcription, outbound voice notes
"""

import os
import json
import subprocess
import threading
import time
from datetime import datetime
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import pyotp

from event_detector import TmuxMonitor, DetectedEvent, EventType
from summarizer import Summarizer

app = Flask(__name__)

# Twilio client
twilio_client = None

# Session state
user_sessions = {}  # phone -> session state
pending_events = {}  # phone -> list of events awaiting response

# Config
TOTP_SECRET = os.getenv("TOTP_SECRET", pyotp.random_base32())
TMUX_SESSIONS = json.loads(os.getenv("TMUX_SESSIONS", '[{"name": "main", "pane": "%0"}]'))
YOUR_WHATSAPP = os.getenv("YOUR_WHATSAPP", "")  # Your number: whatsapp:+1234567890
TWILIO_WHATSAPP = os.getenv("TWILIO_WHATSAPP", "")  # Twilio sandbox: whatsapp:+14155238886


def get_twilio_client():
    global twilio_client
    if twilio_client is None:
        twilio_client = Client(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN")
        )
    return twilio_client


def send_whatsapp(to: str, message: str):
    """Send a WhatsApp message."""
    client = get_twilio_client()
    client.messages.create(
        from_=TWILIO_WHATSAPP,
        to=to,
        body=message
    )
    print(f"[Tower → WhatsApp] {message[:100]}...")


def verify_totp(code: str) -> bool:
    """Verify TOTP code."""
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.verify(code, valid_window=1)


def get_session_status_text() -> str:
    """Get current status of all sessions as text."""
    from event_detector import capture_tmux_pane

    lines = ["📡 *Tower Status Report*\n"]

    for i, session in enumerate(TMUX_SESSIONS, 1):
        output = capture_tmux_pane(session["pane"], lines=20)

        if not output.strip():
            status = "⚪ idle"
        else:
            output_lower = output.lower()
            if any(x in output_lower for x in ["error", "failed", "exception"]):
                status = "🔴 error"
            elif any(x in output_lower for x in ["waiting", "approve", "confirm", "y/n"]):
                status = "🟡 waiting for input"
            elif any(x in output_lower for x in ["complete", "done", "finished", "pushed"]):
                status = "🟢 completed"
            else:
                status = "🔵 working"

        lines.append(f"{i}. *{session['name']}* - {status}")

    lines.append("\n_Reply with a number for details, or a command._")
    return "\n".join(lines)


def get_session_detail(session_num: int) -> str:
    """Get detailed status for a specific session."""
    from event_detector import capture_tmux_pane

    if session_num < 1 or session_num > len(TMUX_SESSIONS):
        return f"No session {session_num}. I have {len(TMUX_SESSIONS)} sessions."

    session = TMUX_SESSIONS[session_num - 1]
    output = capture_tmux_pane(session["pane"], lines=30)

    # Get last meaningful lines
    lines = [l.strip() for l in output.split("\n") if l.strip()][-10:]
    recent = "\n".join(lines) if lines else "(no recent output)"

    return f"*Session {session_num}: {session['name']}*\n\n```\n{recent[:1000]}\n```"


def send_to_session(session_num: int, instruction: str) -> str:
    """Send instruction to a tmux session."""
    if session_num < 1 or session_num > len(TMUX_SESSIONS):
        return f"No session {session_num}."

    session = TMUX_SESSIONS[session_num - 1]
    pane = session["pane"]

    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", pane, instruction, "Enter"],
            check=True,
            timeout=5,
        )
        return f"✅ Sent to {session['name']}: `{instruction}`"
    except Exception as e:
        return f"❌ Failed to send: {e}"


def handle_command(phone: str, text: str) -> str:
    """Process a command from the user."""
    text_lower = text.lower().strip()
    session = user_sessions.get(phone, {})

    # Check if authenticated
    if not session.get("authenticated"):
        # Check if this is a TOTP code
        if text.isdigit() and len(text) == 6:
            if verify_totp(text):
                user_sessions[phone] = {"authenticated": True, "auth_time": time.time()}
                return "🔓 Authenticated.\n\n" + get_session_status_text()
            else:
                return "❌ Invalid code. Try again."
        else:
            return "🔐 Tower here. Send your 6-digit code to authenticate."

    # Authenticated - process commands

    # Status request
    if text_lower in ["status", "s", "sitrep", "report", "?"]:
        return get_session_status_text()

    # Session number for details
    if text.isdigit():
        return get_session_detail(int(text))

    # Approve/continue
    if text_lower in ["approve", "yes", "y", "continue", "go", "ok"]:
        # Find session waiting for input
        for i, sess in enumerate(TMUX_SESSIONS, 1):
            from event_detector import capture_tmux_pane
            output = capture_tmux_pane(sess["pane"], lines=10).lower()
            if any(x in output for x in ["waiting", "approve", "confirm", "y/n"]):
                return send_to_session(i, "yes")
        return "No session is waiting for approval."

    # Retry
    if text_lower in ["retry", "again", "rerun"]:
        for i, sess in enumerate(TMUX_SESSIONS, 1):
            from event_detector import capture_tmux_pane
            output = capture_tmux_pane(sess["pane"], lines=10).lower()
            if any(x in output for x in ["error", "failed"]):
                return send_to_session(i, "retry")
        return "No session has errors to retry."

    # Stop/abort
    if text_lower in ["stop", "abort", "cancel", "kill"]:
        return "Which session? Reply with the number."

    # Direct command: "1: do something" or "1 do something"
    if text[0].isdigit():
        parts = text.split(":", 1) if ":" in text else text.split(" ", 1)
        if len(parts) == 2:
            try:
                session_num = int(parts[0].strip())
                instruction = parts[1].strip()
                return send_to_session(session_num, instruction)
            except ValueError:
                pass

    # Help
    if text_lower in ["help", "h", "commands", "?"]:
        return """*Tower Commands*

📊 *Status*
`status` - Get all session statuses
`1`, `2`, etc - Get details for session

✅ *Actions*
`approve` - Approve waiting session
`retry` - Retry failed session
`1: <instruction>` - Send command to session 1

🔄 *Other*
`help` - This message
`logout` - End session"""

    # Logout
    if text_lower in ["logout", "bye", "exit"]:
        user_sessions.pop(phone, None)
        return "👋 Logged out. Send your code to reconnect."

    # Unknown
    return "Didn't understand that. Reply `help` for commands."


@app.route("/whatsapp/webhook", methods=["POST"])
def whatsapp_webhook():
    """Handle incoming WhatsApp messages."""
    from_number = request.form.get("From", "")
    body = request.form.get("Body", "").strip()
    media_url = request.form.get("MediaUrl0", "")  # Voice message URL

    print(f"[WhatsApp → Tower] {from_number}: {body[:100]}")

    # TODO: Handle voice messages (transcribe with Whisper)
    if media_url:
        response_text = "🎤 Voice messages coming soon. Please send text for now."
    else:
        response_text = handle_command(from_number, body)

    # Send response
    resp = MessagingResponse()
    resp.message(response_text)

    return Response(str(resp), mimetype="text/xml")


@app.route("/health", methods=["GET"])
def health():
    """Health check."""
    return {"status": "ok", "sessions": len(TMUX_SESSIONS)}


# === Outbound alerts (Tower → You) ===

class WhatsAppAlerter:
    """Monitors sessions and sends WhatsApp alerts on events."""

    def __init__(self, target_phone: str):
        self.target_phone = target_phone
        self.summarizer = Summarizer()
        self.monitors = []
        self.running = False

    def on_event(self, session_name: str, event: DetectedEvent):
        """Handle detected event - send WhatsApp alert."""
        # Generate summary
        summary = self.summarizer.summarize(event)

        # Build message
        emoji = "🔴" if event.event_type == EventType.ERROR else "🟡"

        message = f"""{emoji} *Tower Alert: {session_name}*

{summary.speech_text}

*Options:*
"""
        for opt in summary.options:
            message += f"• Reply `{opt.key}` to {opt.label}\n"

        message += "\n_Or reply with a custom instruction._"

        send_whatsapp(self.target_phone, message)

    def start(self):
        """Start monitoring all sessions."""
        self.running = True

        for session in TMUX_SESSIONS:
            monitor = TmuxMonitor(session["pane"])

            def make_callback(name):
                return lambda event: self.on_event(name, event)

            thread = threading.Thread(
                target=monitor.run,
                args=(make_callback(session["name"]),),
                daemon=True
            )
            thread.start()
            self.monitors.append((monitor, thread))
            print(f"[Tower] Monitoring {session['name']} ({session['pane']})")

    def stop(self):
        self.running = False


def print_setup_info():
    """Print setup instructions."""
    totp = pyotp.TOTP(TOTP_SECRET)

    print("\n" + "=" * 60)
    print("TOWER - WhatsApp Edition")
    print("=" * 60)

    print("\n📱 TOTP Setup:")
    print(f"   Secret: {TOTP_SECRET}")
    print(f"   Current code: {totp.now()}")

    print("\n📲 Twilio WhatsApp Sandbox:")
    print("   1. Go to: https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn")
    print("   2. Send the join code to the sandbox number")
    print(f"   3. Set webhook to: https://yourserver.com/whatsapp/webhook")

    print("\n🖥️  Sessions:")
    for s in TMUX_SESSIONS:
        print(f"   • {s['name']}: pane {s['pane']}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print_setup_info()

    # Start alerter if phone configured
    if YOUR_WHATSAPP:
        alerter = WhatsAppAlerter(YOUR_WHATSAPP)
        alerter.start()
        print(f"\n[Tower] Alerts will go to: {YOUR_WHATSAPP}")
    else:
        print("\n[Tower] No YOUR_WHATSAPP set - inbound only mode")

    print("\n[Tower] Starting webhook server on :5000...")
    app.run(host="0.0.0.0", port=5000, debug=False)

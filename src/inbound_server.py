"""
Tower - Air traffic control for your AI coding agents.

Call in, authenticate with TOTP, get status updates on all your Claude sessions,
and issue commands by voice. Like calling the tower for a sitrep on your fleet.
"""

import os
import json
import subprocess
from datetime import datetime
from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
import pyotp

from event_detector import capture_tmux_pane, strip_ansi
from summarizer import Summarizer

app = Flask(__name__)

# In-memory session state (use Redis in production)
call_sessions = {}

# TOTP secret - generate once with: pyotp.random_base32()
# Store in .env, share with your authenticator app
TOTP_SECRET = os.getenv("TOTP_SECRET", pyotp.random_base32())

# Registered tmux sessions to monitor
TMUX_SESSIONS = json.loads(os.getenv("TMUX_SESSIONS", '[{"name": "main", "pane": "%0"}]'))


def verify_totp(code: str) -> bool:
    """Verify a TOTP code."""
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.verify(code, valid_window=1)  # Allow 30s drift


def get_all_session_statuses() -> list[dict]:
    """Get current status of all registered tmux sessions."""
    statuses = []
    summarizer = Summarizer()

    for session in TMUX_SESSIONS:
        output = capture_tmux_pane(session["pane"], lines=30)

        if not output.strip():
            status = "idle or not running"
            detail = ""
        else:
            # Quick classification without full summarization
            output_lower = output.lower()
            if any(x in output_lower for x in ["error", "failed", "exception"]):
                status = "hit a problem"
                # Get the error line
                for line in output.split("\n"):
                    if any(x in line.lower() for x in ["error", "failed"]):
                        detail = line.strip()[:100]
                        break
                else:
                    detail = "check the logs"
            elif any(x in output_lower for x in ["waiting", "approve", "confirm", "y/n"]):
                status = "waiting for your input"
                detail = output.split("\n")[-3] if output.split("\n") else ""
            elif any(x in output_lower for x in ["complete", "done", "finished", "pushed"]):
                status = "finished its task"
                detail = ""
            else:
                status = "working"
                detail = ""

        statuses.append({
            "name": session["name"],
            "pane": session["pane"],
            "status": status,
            "detail": detail,
            "raw_output": output[-500:],
        })

    return statuses


def generate_status_speech(statuses: list[dict]) -> str:
    """Generate a casual spoken status update."""
    if not statuses:
        return "Looks like nothing's running right now. Pretty quiet."

    lines = []
    needs_attention = []

    for i, s in enumerate(statuses, 1):
        name = s["name"]
        status = s["status"]

        if status == "hit a problem":
            lines.append(f"Session {i}, {name}, hit a snag. {s['detail'][:50] if s['detail'] else 'Check the logs.'}")
            needs_attention.append(i)
        elif status == "waiting for your input":
            lines.append(f"Session {i}, {name}, is waiting on you.")
            needs_attention.append(i)
        elif status == "finished its task":
            lines.append(f"Session {i}, {name}, finished up. All good there.")
        elif status == "idle or not running":
            lines.append(f"Session {i}, {name}, is idle.")
        else:
            lines.append(f"Session {i}, {name}, is humming along.")

    speech = " ".join(lines)

    if needs_attention:
        speech += f" Want details on any of these? Just say the session number."
    else:
        speech += " Everything's looking good. Anything else?"

    return speech


# Tower greetings - ATC meets old friend
GREETINGS = [
    "Tower here. Good to hear from you.",
    "Tower. You're loud and clear.",
    "This is Tower. Ready when you are.",
    "Tower online. What do you need?",
]


@app.route("/voice/answer", methods=["POST"])
def answer_call():
    """Handle incoming call - start with greeting and TOTP prompt."""
    response = VoiceResponse()

    call_sid = request.form.get("CallSid", "unknown")
    call_sessions[call_sid] = {"authenticated": False, "attempts": 0}

    # Casual greeting
    import random
    greeting = random.choice(GREETINGS)
    response.say(greeting, voice="Polly.Matthew")  # Natural male voice

    # Ask for TOTP
    gather = Gather(
        num_digits=6,
        action="/voice/verify",
        method="POST",
        timeout=10,
    )
    gather.say("What's your code?", voice="Polly.Matthew")
    response.append(gather)

    # If no input
    response.say("Didn't catch that. Try again.", voice="Polly.Matthew")
    response.redirect("/voice/answer")

    return Response(str(response), mimetype="text/xml")


@app.route("/voice/verify", methods=["POST"])
def verify_code():
    """Verify TOTP and proceed to status update."""
    response = VoiceResponse()

    call_sid = request.form.get("CallSid", "unknown")
    digits = request.form.get("Digits", "")

    session = call_sessions.get(call_sid, {"attempts": 0})
    session["attempts"] += 1

    if verify_totp(digits):
        session["authenticated"] = True
        call_sessions[call_sid] = session

        response.say("Authenticated. You're clear.", voice="Polly.Matthew")
        response.pause(length=1)

        # Get and speak status
        statuses = get_all_session_statuses()
        session["statuses"] = statuses
        call_sessions[call_sid] = session

        status_speech = generate_status_speech(statuses)

        gather = Gather(
            input="speech dtmf",
            action="/voice/command",
            method="POST",
            timeout=5,
            speech_timeout="auto",
        )
        gather.say(f"Here's your sitrep. {status_speech}", voice="Polly.Matthew")
        response.append(gather)

        response.say("Still there? I'll hang up if you're done.", voice="Polly.Matthew")
        response.hangup()

    else:
        if session["attempts"] >= 3:
            response.say("Too many tries. Talk later.", voice="Polly.Matthew")
            response.hangup()
        else:
            response.say("That's not it. Try again.", voice="Polly.Matthew")
            gather = Gather(
                num_digits=6,
                action="/voice/verify",
                method="POST",
                timeout=10,
            )
            gather.say("What's your code?", voice="Polly.Matthew")
            response.append(gather)

    return Response(str(response), mimetype="text/xml")


@app.route("/voice/command", methods=["POST"])
def handle_command():
    """Handle voice or DTMF commands after authentication."""
    response = VoiceResponse()

    call_sid = request.form.get("CallSid", "unknown")
    session = call_sessions.get(call_sid, {})

    if not session.get("authenticated"):
        response.say("Nice try. Bye.", voice="Polly.Matthew")
        response.hangup()
        return Response(str(response), mimetype="text/xml")

    # Get the input (speech or digits)
    speech = request.form.get("SpeechResult", "").lower()
    digits = request.form.get("Digits", "")

    statuses = session.get("statuses", [])

    # Parse commands
    if digits:
        # DTMF: session number
        try:
            session_num = int(digits)
            if 1 <= session_num <= len(statuses):
                s = statuses[session_num - 1]
                response.say(
                    f"Session {session_num}, {s['name']}. Status: {s['status']}. "
                    f"Last output was: {s['raw_output'][-200:] if s['raw_output'] else 'nothing recent'}",
                    voice="Polly.Matthew"
                )
        except ValueError:
            response.say("Didn't get that.", voice="Polly.Matthew")

    elif speech:
        # Voice command parsing
        if any(x in speech for x in ["bye", "done", "hang up", "later"]):
            response.say("Alright, catch you later.", voice="Polly.Matthew")
            response.hangup()
            return Response(str(response), mimetype="text/xml")

        elif any(x in speech for x in ["approve", "yes", "continue", "go ahead"]):
            # Find session needing approval and send "yes"
            for i, s in enumerate(statuses):
                if s["status"] == "waiting for your input":
                    pane = s["pane"]
                    subprocess.run(
                        ["tmux", "send-keys", "-t", pane, "yes", "Enter"],
                        timeout=5,
                    )
                    response.say(f"Done. Told session {i+1} to continue.", voice="Polly.Matthew")
                    break
            else:
                response.say("Nothing's waiting for approval right now.", voice="Polly.Matthew")

        elif any(x in speech for x in ["retry", "try again"]):
            for i, s in enumerate(statuses):
                if s["status"] == "hit a problem":
                    pane = s["pane"]
                    subprocess.run(
                        ["tmux", "send-keys", "-t", pane, "retry", "Enter"],
                        timeout=5,
                    )
                    response.say(f"Told session {i+1} to retry.", voice="Polly.Matthew")
                    break

        elif any(x in speech for x in ["stop", "abort", "kill"]):
            response.say("Which session? Say the number.", voice="Polly.Matthew")

        elif any(x in speech for x in ["status", "update", "what's happening"]):
            statuses = get_all_session_statuses()
            session["statuses"] = statuses
            call_sessions[call_sid] = session
            status_speech = generate_status_speech(statuses)
            response.say(status_speech, voice="Polly.Matthew")

        else:
            # Try to extract a session number
            for i in range(1, 10):
                if str(i) in speech or f"session {i}" in speech:
                    if i <= len(statuses):
                        s = statuses[i - 1]
                        response.say(
                            f"Session {i}, {s['name']}. {s['status']}.",
                            voice="Polly.Matthew"
                        )
                    break
            else:
                response.say("Didn't catch that. Say a session number or a command.", voice="Polly.Matthew")

    # Continue listening
    gather = Gather(
        input="speech dtmf",
        action="/voice/command",
        method="POST",
        timeout=5,
        speech_timeout="auto",
    )
    gather.say("What else?", voice="Polly.Matthew")
    response.append(gather)

    response.say("Alright, I'll let you go. Later.", voice="Polly.Matthew")
    response.hangup()

    return Response(str(response), mimetype="text/xml")


@app.route("/voice/status", methods=["GET"])
def status():
    """Health check endpoint."""
    return {"status": "ok", "sessions": len(TMUX_SESSIONS)}


def print_totp_setup():
    """Print TOTP setup info."""
    totp = pyotp.TOTP(TOTP_SECRET)
    uri = totp.provisioning_uri(name="tower", issuer_name="Tower")

    print("\n" + "=" * 60)
    print("TOTP SETUP")
    print("=" * 60)
    print(f"\nSecret: {TOTP_SECRET}")
    print(f"\nAdd to your authenticator app, or use this URI:")
    print(f"{uri}")
    print(f"\nCurrent code: {totp.now()}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print_totp_setup()

    print("Tower is online.")
    print("Point Twilio webhook to: https://your-ngrok.io/voice/answer")
    print("\nRegistered sessions:")
    for s in TMUX_SESSIONS:
        print(f"  - {s['name']}: pane {s['pane']}")
    print()

    app.run(host="0.0.0.0", port=5000, debug=True)

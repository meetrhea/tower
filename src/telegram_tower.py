"""
Tower via Telegram - Free, no Twilio required.

Setup:
1. Message @BotFather on Telegram
2. /newbot → name it "Tower" → get your token
3. Add TELEGRAM_BOT_TOKEN to .env
4. Run this script
5. Message your bot

That's it. No Twilio, no webhooks to configure, no sandbox.
"""

import os
import json
import subprocess
import threading
import time
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import pyotp

# Import our modules
import sys
sys.path.insert(0, os.path.dirname(__file__))
from event_detector import TmuxMonitor, DetectedEvent, EventType, capture_tmux_pane
from summarizer import Summarizer

# Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TOTP_SECRET = os.getenv("TOTP_SECRET", pyotp.random_base32())
TMUX_SESSIONS = json.loads(os.getenv("TMUX_SESSIONS", '[{"name": "main", "pane": "%0"}]'))
AUTHORIZED_USER_ID = os.getenv("TELEGRAM_USER_ID", "")  # Your Telegram user ID

# Session state
user_sessions = {}  # user_id -> session state

# Bot application (set after init)
bot_app = None


def verify_totp(code: str) -> bool:
    """Verify TOTP code."""
    totp = pyotp.TOTP(TOTP_SECRET)
    return totp.verify(code, valid_window=1)


def is_authorized(user_id: int) -> bool:
    """Check if user is authorized (TOTP authenticated or pre-authorized)."""
    # If TELEGRAM_USER_ID is set, only that user can use the bot
    if AUTHORIZED_USER_ID:
        return str(user_id) == AUTHORIZED_USER_ID
    return True  # Allow anyone if not configured (they still need TOTP)


def get_session_status_text() -> str:
    """Get current status of all sessions as formatted text."""
    lines = ["📡 *Tower Status Report*\n"]

    for i, session in enumerate(TMUX_SESSIONS, 1):
        output = capture_tmux_pane(session["pane"], lines=20)

        if not output.strip():
            status = "⚪ idle"
        else:
            output_lower = output.lower()
            if any(x in output_lower for x in ["error", "failed", "exception", "traceback"]):
                status = "🔴 error"
            elif any(x in output_lower for x in ["waiting", "approve", "confirm", "y/n", "[y/n]"]):
                status = "🟡 waiting"
            elif any(x in output_lower for x in ["complete", "done", "finished", "pushed", "success"]):
                status = "🟢 done"
            else:
                status = "🔵 working"

        lines.append(f"`{i}.` *{session['name']}* — {status}")

    lines.append("\n_Reply with a number for details, or send a command._")
    return "\n".join(lines)


def get_session_detail(session_num: int) -> str:
    """Get detailed status for a specific session."""
    if session_num < 1 or session_num > len(TMUX_SESSIONS):
        return f"No session {session_num}. I have {len(TMUX_SESSIONS)} active."

    session = TMUX_SESSIONS[session_num - 1]
    output = capture_tmux_pane(session["pane"], lines=40)

    # Get last meaningful lines
    lines = [l.strip() for l in output.split("\n") if l.strip()][-15:]
    recent = "\n".join(lines) if lines else "(no recent output)"

    # Truncate if too long for Telegram
    if len(recent) > 3000:
        recent = recent[-3000:]

    return f"*Session {session_num}: {session['name']}*\n\n```\n{recent}\n```"


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
        return f"✅ Sent to *{session['name']}*:\n`{instruction}`"
    except Exception as e:
        return f"❌ Failed: {e}"


def get_ai_summary(session_num: int) -> str:
    """Get an AI-generated summary of what's happening in a session."""
    if session_num < 1 or session_num > len(TMUX_SESSIONS):
        return f"No session {session_num}."

    session = TMUX_SESSIONS[session_num - 1]
    output = capture_tmux_pane(session["pane"], lines=50)

    if not output.strip():
        return f"*{session['name']}* is idle - no recent output."

    # Create a mock event for the summarizer
    event = DetectedEvent(
        event_type=EventType.NORMAL,
        raw_output=output,
        key_lines=output.strip().split("\n")[-5:],
        confidence=1.0,
        timestamp=time.time(),
    )

    summarizer = Summarizer()
    summary = summarizer.summarize(event)

    response = f"*{session['name']}* — AI Summary:\n\n{summary.speech_text}"

    if summary.options:
        response += "\n\n*Suggested actions:*"
        for opt in summary.options[:3]:
            response += f"\n• `{opt.key}`: {opt.label}"

    return response


# === Telegram Handlers ===

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        await update.message.reply_text("🚫 Unauthorized.")
        return

    await update.message.reply_text(
        "🗼 *Tower Online*\n\n"
        "Send your 6-digit code to authenticate.\n\n"
        "_Your AI agents are standing by._",
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = """🗼 *Tower Commands*

*Status*
`/status` — All session statuses
`/s` — Same as /status
`1`, `2`, etc — Session details
`/ai 1` — AI summary of session 1

*Actions*
`/approve` — Approve waiting session
`/retry` — Retry failed session
`1: your instruction` — Send to session 1

*Session*
`/logout` — End your session
`/help` — This message

*Examples:*
`1: run the tests`
`2: yes, deploy it`
`/ai 1` — "What's happening in session 1?"
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})

    if not session.get("authenticated"):
        await update.message.reply_text("🔐 Send your 6-digit code first.")
        return

    await update.message.reply_text(get_session_status_text(), parse_mode="Markdown")


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ai command - get AI summary of a session."""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})

    if not session.get("authenticated"):
        await update.message.reply_text("🔐 Send your 6-digit code first.")
        return

    # Parse session number from args
    if context.args and context.args[0].isdigit():
        session_num = int(context.args[0])
    else:
        await update.message.reply_text("Usage: `/ai 1` for session 1", parse_mode="Markdown")
        return

    await update.message.reply_text("🤖 Analyzing...", parse_mode="Markdown")
    summary = get_ai_summary(session_num)
    await update.message.reply_text(summary, parse_mode="Markdown")


async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /approve command."""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})

    if not session.get("authenticated"):
        await update.message.reply_text("🔐 Send your 6-digit code first.")
        return

    # Find session waiting for input
    for i, sess in enumerate(TMUX_SESSIONS, 1):
        output = capture_tmux_pane(sess["pane"], lines=10).lower()
        if any(x in output for x in ["waiting", "approve", "confirm", "y/n", "[y/n]"]):
            result = send_to_session(i, "yes")
            await update.message.reply_text(result, parse_mode="Markdown")
            return

    await update.message.reply_text("No session is waiting for approval.")


async def retry_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /retry command."""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})

    if not session.get("authenticated"):
        await update.message.reply_text("🔐 Send your 6-digit code first.")
        return

    for i, sess in enumerate(TMUX_SESSIONS, 1):
        output = capture_tmux_pane(sess["pane"], lines=10).lower()
        if any(x in output for x in ["error", "failed", "exception"]):
            result = send_to_session(i, "retry")
            await update.message.reply_text(result, parse_mode="Markdown")
            return

    await update.message.reply_text("No session has errors to retry.")


async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /logout command."""
    user_id = update.effective_user.id
    user_sessions.pop(user_id, None)
    await update.message.reply_text("👋 Logged out. Send your code to reconnect.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not is_authorized(user_id):
        await update.message.reply_text("🚫 Unauthorized.")
        return

    session = user_sessions.get(user_id, {})

    # Check if authenticated
    if not session.get("authenticated"):
        # Check if this is a TOTP code
        if text.isdigit() and len(text) == 6:
            if verify_totp(text):
                user_sessions[user_id] = {"authenticated": True, "auth_time": time.time()}
                status = get_session_status_text()
                await update.message.reply_text(
                    f"🔓 *Authenticated*\n\n{status}",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ Invalid code. Try again.")
        else:
            await update.message.reply_text("🔐 Send your 6-digit code to authenticate.")
        return

    # Authenticated - process commands
    text_lower = text.lower()

    # Status shortcuts
    if text_lower in ["status", "s", "sitrep", "?"]:
        await update.message.reply_text(get_session_status_text(), parse_mode="Markdown")
        return

    # Session number for details
    if text.isdigit() and len(text) <= 2:
        detail = get_session_detail(int(text))
        await update.message.reply_text(detail, parse_mode="Markdown")
        return

    # Quick approve
    if text_lower in ["approve", "yes", "y", "ok", "go"]:
        for i, sess in enumerate(TMUX_SESSIONS, 1):
            output = capture_tmux_pane(sess["pane"], lines=10).lower()
            if any(x in output for x in ["waiting", "approve", "confirm", "y/n"]):
                result = send_to_session(i, "yes")
                await update.message.reply_text(result, parse_mode="Markdown")
                return
        await update.message.reply_text("No session waiting for approval.")
        return

    # Direct command: "1: do something" or "1 do something"
    if text[0].isdigit():
        parts = text.split(":", 1) if ":" in text else text.split(" ", 1)
        if len(parts) == 2:
            try:
                session_num = int(parts[0].strip())
                instruction = parts[1].strip()
                if instruction:
                    result = send_to_session(session_num, instruction)
                    await update.message.reply_text(result, parse_mode="Markdown")
                    return
            except ValueError:
                pass

    # Unknown command
    await update.message.reply_text(
        "Didn't catch that. Try:\n"
        "• `status` — see all sessions\n"
        "• `1` — details for session 1\n"
        "• `1: run tests` — send command\n"
        "• `/help` — all commands",
        parse_mode="Markdown"
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages - placeholder for Whisper integration."""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})

    if not session.get("authenticated"):
        await update.message.reply_text("🔐 Send your 6-digit code first.")
        return

    # TODO: Download voice file, transcribe with Whisper, process as text
    await update.message.reply_text(
        "🎤 Voice messages coming soon!\n\n"
        "_For now, please type your command._",
        parse_mode="Markdown"
    )


# === Outbound Alerts ===

async def send_alert(user_id: int, message: str):
    """Send an alert to a user."""
    if bot_app:
        await bot_app.bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode="Markdown"
        )


class TelegramAlerter:
    """Monitors sessions and sends Telegram alerts on events."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.summarizer = Summarizer()
        self.running = False
        self.loop = None

    def on_event(self, session_name: str, event: DetectedEvent):
        """Handle detected event - send Telegram alert."""
        summary = self.summarizer.summarize(event)

        emoji = "🔴" if event.event_type == EventType.ERROR else "🟡"

        message = f"{emoji} *Tower Alert: {session_name}*\n\n"
        message += f"{summary.speech_text}\n\n"
        message += "*Options:*\n"

        for opt in summary.options[:3]:
            message += f"• Reply `{opt.key}` — {opt.label}\n"

        message += "\n_Or send a custom instruction._"

        # Schedule the async send in the event loop
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                send_alert(self.user_id, message),
                self.loop
            )

    def start(self, loop):
        """Start monitoring all sessions."""
        self.running = True
        self.loop = loop

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
            print(f"[Tower] Monitoring {session['name']} ({session['pane']})")


def print_setup_info():
    """Print setup instructions."""
    totp = pyotp.TOTP(TOTP_SECRET)

    print("\n" + "=" * 60)
    print("🗼 TOWER - Telegram Edition")
    print("=" * 60)

    print("\n📱 TOTP Setup:")
    print(f"   Secret: {TOTP_SECRET}")
    print(f"   Current code: {totp.now()}")

    print("\n🤖 Telegram Bot Setup:")
    print("   1. Message @BotFather on Telegram")
    print("   2. Send /newbot")
    print("   3. Name your bot (e.g., 'My Tower Bot')")
    print("   4. Copy the token to TELEGRAM_BOT_TOKEN in .env")

    print("\n🔒 Security (Optional):")
    print("   Set TELEGRAM_USER_ID to restrict to your account only")
    print("   (Message @userinfobot to get your ID)")

    print("\n🖥️  Sessions:")
    for s in TMUX_SESSIONS:
        print(f"   • {s['name']}: pane {s['pane']}")

    print("\n" + "=" * 60)


def main():
    """Run the Telegram bot."""
    global bot_app

    from dotenv import load_dotenv
    load_dotenv()

    # Reload config after dotenv
    global TELEGRAM_BOT_TOKEN, TOTP_SECRET, TMUX_SESSIONS, AUTHORIZED_USER_ID
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TOTP_SECRET = os.getenv("TOTP_SECRET", pyotp.random_base32())
    TMUX_SESSIONS = json.loads(os.getenv("TMUX_SESSIONS", '[{"name": "main", "pane": "%0"}]'))
    AUTHORIZED_USER_ID = os.getenv("TELEGRAM_USER_ID", "")

    print_setup_info()

    if not TELEGRAM_BOT_TOKEN:
        print("\n❌ TELEGRAM_BOT_TOKEN not set in .env")
        print("   Get one from @BotFather on Telegram")
        return

    # Build application
    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CommandHandler("status", status_command))
    bot_app.add_handler(CommandHandler("s", status_command))
    bot_app.add_handler(CommandHandler("ai", ai_command))
    bot_app.add_handler(CommandHandler("approve", approve_command))
    bot_app.add_handler(CommandHandler("retry", retry_command))
    bot_app.add_handler(CommandHandler("logout", logout_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    bot_app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Start alerter if user ID configured
    if AUTHORIZED_USER_ID:
        alerter = TelegramAlerter(int(AUTHORIZED_USER_ID))
        # We'll start it after the bot starts
        print(f"\n[Tower] Alerts will go to user ID: {AUTHORIZED_USER_ID}")

    print("\n[Tower] Bot is running. Message your bot on Telegram!")
    print("[Tower] Press Ctrl+C to stop.\n")

    # Run the bot
    bot_app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

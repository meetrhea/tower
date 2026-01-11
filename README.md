# Tower

Air traffic control for your AI coding agents.

Text in. Status out. Voice later.

## Quick Start (WhatsApp MVP)

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Twilio creds

python src/whatsapp_tower.py
```

### Twilio WhatsApp Sandbox Setup

1. Go to [Twilio WhatsApp Sandbox](https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn)
2. Send the join code from your phone to the sandbox number
3. Set the webhook URL to `https://yourserver.com/whatsapp/webhook`
4. Add your TOTP secret to an authenticator app

### Usage

```
You: 847293                    # TOTP code
Tower: 🔓 Authenticated.
       📡 Tower Status Report
       1. main - 🔵 working
       2. infra - 🟡 waiting for input

You: 2                         # Get details
Tower: *Session 2: infra*
       [recent terminal output]

You: approve                   # Approve waiting session
Tower: ✅ Sent to infra: `yes`

You: 1: run the tests again    # Direct command
Tower: ✅ Sent to main: `run the tests again`
```

## Features

| Feature | Status |
|---------|--------|
| WhatsApp text chat | ✅ Now |
| TOTP authentication | ✅ Now |
| Outbound alerts | ✅ Now |
| Voice message input | 🔜 Next |
| Phone calls | 🔜 Later |

## Commands

| Command | Action |
|---------|--------|
| `status` | Get all session statuses |
| `1`, `2`, etc | Get details for session |
| `approve` | Approve waiting session |
| `retry` | Retry failed session |
| `1: <instruction>` | Send command to session 1 |
| `help` | Show commands |
| `logout` | End session |

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│  Your Phone     │────▶│  Twilio         │
│  (WhatsApp)     │◀────│  WhatsApp API   │
└─────────────────┘     └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │  Tower          │
                        │  (Flask app)    │
                        └────────┬────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
     ┌────────▼────────┐ ┌───────▼───────┐ ┌───────▼───────┐
     │  tmux session 1 │ │ tmux session 2│ │ tmux session 3│
     │  (Claude Code)  │ │ (Claude Code) │ │ (Claude Code) │
     └─────────────────┘ └───────────────┘ └───────────────┘
```

## Deployment

```bash
# On your server
gunicorn -w 2 -b 0.0.0.0:5000 src.whatsapp_tower:app

# With systemd (create /etc/systemd/system/tower.service)
[Unit]
Description=Tower - AI Agent Control
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/tower
ExecStart=/path/to/venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 src.whatsapp_tower:app
Restart=always

[Install]
WantedBy=multi-user.target
```

## Roadmap

1. **WhatsApp Text** ← You are here
   - Text commands, status updates, TOTP auth

2. **Voice Messages**
   - Send voice notes, Tower transcribes with Whisper
   - Tower replies with text (or generated voice)

3. **Phone Calls**
   - Call Tower for voice-first interaction
   - Tower calls you on critical alerts

4. **Walkie-Talkie Mode**
   - Push-to-talk across multiple sessions
   - "Channel 2, approve and continue"

## Project Structure

```
src/
  whatsapp_tower.py   # Main app - WhatsApp interface
  inbound_server.py   # Phone calls (future)
  event_detector.py   # tmux monitoring
  summarizer.py       # LLM summaries
  phone_caller.py     # Outbound calls
  main.py             # CLI daemon
```

See [PRD.md](PRD.md) for full specification.

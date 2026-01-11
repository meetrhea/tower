# Tower

Air traffic control for your AI coding agents.

Call in. Authenticate. Get status on all active sessions. Issue commands by voice.

> "Tower, requesting status on all flights."
> "Copy. Flight one is clear, holding pattern. Flight two has an issue on approach..."

## Features

- **Inbound calls**: Call your Tower number anytime to check on your agents
- **TOTP auth**: 6-digit code from your authenticator app
- **Voice commands**: "approve", "retry", "status", session numbers
- **Outbound alerts**: Tower calls you when an agent hits a problem
- **Interaction logging**: Every call logged for preference learning

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Add your API keys, Twilio creds, TOTP secret

# Run Tower
python src/inbound_server.py
```

Point your Twilio phone number's webhook to `https://yourserver.com/voice/answer`

## How It Works

**Inbound (you call Tower):**
1. Tower answers with a greeting
2. You punch in your TOTP code
3. Tower gives you a sitrep on all sessions
4. You issue commands by voice or keypad
5. Tower executes and confirms

**Outbound (Tower calls you):**
1. Agent hits an error, permission prompt, or stall
2. Tower summarizes and calls your phone
3. You respond with a decision
4. Tower sends the instruction back to the agent

## Voice Commands

| Command | Action |
|---------|--------|
| "status" / "update" | Refresh status on all sessions |
| "approve" / "go ahead" | Send approval to waiting session |
| "retry" | Retry failed session |
| "session 2" / press "2" | Get details on specific session |
| "bye" / "done" | Hang up |

## Project Structure

```
src/
  inbound_server.py  - Flask app handling Twilio webhooks
  event_detector.py  - tmux monitoring and event classification
  summarizer.py      - LLM-based summary generation
  phone_caller.py    - Outbound calls + local TTS fallback
  main.py            - Outbound-only monitoring daemon
logs/
  interactions.jsonl - Logged interactions
```

## Configuration

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_FROM=+1234567890
PHONE_TO=+1234567890
TOTP_SECRET=YOUR32CHARACTERBASE32SECRET
TMUX_SESSIONS='[{"name": "infra", "pane": "%0"}, {"name": "trading", "pane": "%1"}]'
```

## Deployment

Tower runs as a Flask app. For your server:

```bash
# With gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 src.inbound_server:app

# Or with systemd service
# See deploy/tower.service
```

See [PRD.md](PRD.md) for full specification.

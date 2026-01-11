# Tower

Air traffic control for your AI coding agents.

Text your bot. Get status. Issue commands. All from your phone.

## Why Tower?

You're running Claude Code sessions on a server. They hit errors, need approvals, get stuck. You shouldn't have to SSH in every time. Just text Tower.

**The summaries are the product.** If Tower just forwarded terminal garbage, you'd ignore it. Instead, Tower uses AI to translate what's happening into clear, actionable intelligence:

> ❌ Bad: "FAILED tests/test_auth.py::test_login - AssertionError"
>
> ✅ Good: "Auth tests failed. Login returns 401 instead of 200 - the JWT secret changed but test fixtures still use the old one. Signup and password reset also fail because they depend on login working."

Tower has to be impressive to see adoption. Every alert should make you think "this actually understands what's happening."

---

## Quick Start (Telegram - Free, 2 minutes)

> **Full setup guide with troubleshooting: [SETUP.md](SETUP.md)**

```bash
git clone https://github.com/meetrhea/tower.git
cd tower
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 1. Create your bot
1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot`
3. Name it "Tower" (or whatever)
4. Copy the token to `TELEGRAM_BOT_TOKEN` in `.env`

### 2. Get your user ID (optional but recommended)
1. Message [@userinfobot](https://t.me/userinfobot)
2. Copy your ID to `TELEGRAM_USER_ID` in `.env`
3. This restricts the bot to only respond to you

### 3. Set up TOTP
```bash
python -c "import pyotp; print(pyotp.random_base32())"
```
Add the secret to `.env` and your authenticator app.

### 4. Run it
```bash
python src/telegram_tower.py
```

### 5. Use it
Message your bot:

```
You: 847293                      # Your TOTP code
Tower: 🔓 Authenticated
       📡 Tower Status Report
       1. main — 🔵 working
       2. infra — 🟡 waiting

You: 2                           # Get details
Tower: *Session 2: infra*
       [last 15 lines of terminal output]

You: /ai 2                       # AI summary
Tower: 🤖 Analyzing...
       Auth tests failed. Login returns 401 - looks like
       the JWT secret changed but test fixtures weren't
       updated. Signup and reset also fail because they
       depend on login.

       Suggested actions:
       • 1: Update test fixtures
       • 2: Revert JWT change
       • 9: Stop and investigate

You: approve                     # Approve waiting session
Tower: ✅ Sent to infra: `yes`

You: 1: run the tests again      # Direct command
Tower: ✅ Sent to main: `run the tests again`
```

---

## Commands

| Command | What it does |
|---------|--------------|
| `/status` or `status` | All session statuses |
| `1`, `2`, etc | Terminal output for that session |
| `/ai 1` | AI-powered summary of session 1 |
| `/approve` | Send "yes" to waiting session |
| `/retry` | Retry failed session |
| `1: your instruction` | Send command to session 1 |
| `/help` | All commands |
| `/logout` | End session |

---

## Features

| Feature | Status |
|---------|--------|
| Telegram text chat | ✅ Ready |
| TOTP authentication | ✅ Ready |
| AI-powered summaries | ✅ Ready |
| Outbound alerts | ✅ Ready |
| Voice message input | 🔜 Next |
| WhatsApp (via Twilio) | ✅ Alternative |
| Phone calls | 🔜 Later |

---

## The AI Summaries

Tower's value is in translation. Raw terminal output is noise. Good summaries are signal.

**Every summary must be:**
- **Specific** — Not "error occurred", but "3 auth tests failed, login returns 401"
- **Insightful** — Identify root causes, not just symptoms
- **Actionable** — Clear next steps, not generic "continue/stop"
- **Confident** — Expert assistant, not hesitant helper

See `src/summarizer.py` for the prompt engineering.

---

## Architecture

```
┌─────────────────┐
│  Your Phone     │
│  (Telegram)     │
└────────┬────────┘
         │
┌────────▼────────┐
│  Telegram API   │
│  (free)         │
└────────┬────────┘
         │
┌────────▼────────┐
│  Tower          │
│  (your server)  │
└────────┬────────┘
         │
    ┌────┴────┬─────────┐
    │         │         │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐
│ tmux  │ │ tmux  │ │ tmux  │
│ pane  │ │ pane  │ │ pane  │
└───────┘ └───────┘ └───────┘
```

---

## Deployment

```bash
# Run directly
python src/telegram_tower.py

# Or with systemd
sudo nano /etc/systemd/system/tower.service
```

```ini
[Unit]
Description=Tower - AI Agent Control
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/tower
Environment=PATH=/path/to/venv/bin
ExecStart=/path/to/venv/bin/python src/telegram_tower.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable tower
sudo systemctl start tower
```

---

## Roadmap

1. **Telegram Text** ← You are here
   - Text commands, AI summaries, TOTP auth

2. **Voice Messages**
   - Send voice notes, Tower transcribes with Whisper
   - Reply with voice or text

3. **Phone Calls**
   - Call Tower for voice-first interaction
   - Tower calls you on critical alerts

4. **Walkie-Talkie Mode**
   - Push-to-talk across multiple sessions
   - "Channel 2, approve and continue"

---

## Alternatives

### WhatsApp (requires Twilio)
```bash
python src/whatsapp_tower.py
```
Needs Twilio account, sandbox setup, webhook URL. More steps but works.

### Phone Calls (future)
```bash
python src/inbound_server.py
```
Full ATC experience. Call in, TOTP, get sitrep, voice commands.

---

## Project Structure

```
src/
  telegram_tower.py   # Main - Telegram bot (recommended)
  whatsapp_tower.py   # Alternative - WhatsApp via Twilio
  inbound_server.py   # Future - phone calls
  summarizer.py       # AI summaries (THE PRODUCT)
  event_detector.py   # tmux monitoring
  phone_caller.py     # Outbound calls
  main.py             # CLI daemon
```

---

## Contributing

The most important file is `src/summarizer.py`. The prompt there determines whether Tower is useful or useless. If you can make the summaries better, that's the highest-leverage contribution.

See [PRD.md](PRD.md) for full specification.

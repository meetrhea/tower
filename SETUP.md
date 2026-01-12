# Tower Setup Guide

Get Tower running in 5 minutes.

## Prerequisites

- Python 3.10+
- tmux with Claude Code sessions running
- A phone with Telegram

---

## Step 1: Clone and Install

```bash
git clone https://github.com/meetrhea/tower.git
cd tower
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Step 2: Create Your Telegram Bot

1. Open Telegram on your phone
2. Search for **@BotFather** and start a chat
3. Send `/newbot`
4. Choose a name (e.g., "My Tower")
5. Choose a username (e.g., "my_tower_bot")
6. **Copy the token** — looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

---

## Step 3: Get Your Telegram User ID (Recommended)

This restricts the bot to only respond to you.

1. Search for **@userinfobot** on Telegram
2. Start a chat, it will reply with your user ID
3. **Copy your ID** — looks like `123456789`

---

## Step 4: Generate TOTP Secret

```bash
python -c "import pyotp; print(pyotp.random_base32())"
```

Copy the output (e.g., `JBSWY3DPEHPK3PXP`).

Add this to your authenticator app:
- Open Google Authenticator / Authy / 1Password
- Add new account manually
- Name: "Tower"
- Secret: (paste the secret)

---

## Step 5: Configure Environment

```bash
cp .env.example .env
nano .env  # or your preferred editor
```

Fill in:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-your-key-here
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TOTP_SECRET=JBSWY3DPEHPK3PXP

# Recommended - restricts bot to you only
TELEGRAM_USER_ID=123456789

# Your tmux sessions
TMUX_SESSIONS='[{"name": "main", "pane": "%0"}]'
```

### Finding Your tmux Pane IDs

```bash
# List all panes
tmux list-panes -a

# Output looks like:
# %0: [180x45] [history 1000/10000, 50000 bytes]
# %1: [180x45] [history 500/10000, 25000 bytes]
```

Use the `%0`, `%1`, etc. in your config:

```bash
TMUX_SESSIONS='[{"name": "claude-main", "pane": "%0"}, {"name": "claude-infra", "pane": "%1"}]'
```

---

## Step 6: Run Tower

```bash
python src/telegram_tower.py
```

You should see:

```
============================================================
🗼 TOWER - Telegram Edition
============================================================

📱 TOTP Setup:
   Secret: JBSWY3DPEHPK3PXP
   Current code: 847293

🖥️  Sessions:
   • main: pane %0

[Tower] Bot is running. Message your bot on Telegram!
```

---

## Step 7: Test It

1. Open Telegram
2. Find your bot (search for the username you created)
3. Send `/start`
4. Send your 6-digit TOTP code from your authenticator
5. You're in! Try `status` or `/ai 1`

---

## Running as a Service (Production)

**Important:** Tower must run locally on the same machine as your Claude Code tmux sessions. It cannot run in Docker/Coolify because it needs direct access to tmux.

### Option A: systemd (Recommended)

A service file is included in the repo:

```bash
# Edit the service file to match your paths (already configured for dshanklin)
nano tower.service

# Copy to systemd
sudo cp tower.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable tower
sudo systemctl start tower

# Check status
sudo systemctl status tower

# View logs
journalctl -u tower -f
```

### Option B: tmux (simple)

```bash
tmux new-session -d -s tower 'cd /path/to/tower && source venv/bin/activate && python src/telegram_tower.py'
```

### Option C: screen

```bash
screen -dmS tower bash -c 'cd /path/to/tower && source venv/bin/activate && python src/telegram_tower.py'
```

---

## Troubleshooting

### "TELEGRAM_BOT_TOKEN not set"
Make sure your `.env` file exists and has the token:
```bash
cat .env | grep TELEGRAM
```

### "No session X"
Check your tmux pane IDs match:
```bash
tmux list-panes -a
```

### Bot doesn't respond
1. Make sure the bot is running (`python src/telegram_tower.py`)
2. Check you're messaging the right bot
3. If `TELEGRAM_USER_ID` is set, make sure it's your ID

### TOTP code rejected
1. Check your phone's time is correct (TOTP is time-based)
2. Regenerate the secret and re-add to authenticator:
   ```bash
   python -c "import pyotp; print(pyotp.random_base32())"
   ```

### Can't find tmux panes
Make sure tmux is running and you're in the right session:
```bash
tmux ls                    # List sessions
tmux attach -t sessionname  # Attach to session
tmux list-panes -a         # List all panes across sessions
```

---

## Step 8: Configure Claude Code Hooks (Optional but Recommended)

Hooks provide **instant notifications** instead of waiting for tmux polling (2 second delay).

### Add Tower hooks to Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/home/YOUR_USERNAME/repos-meetrhea/tower/hooks/tower-hook.sh"
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "permission_prompt",
        "hooks": [
          {
            "type": "command",
            "command": "/home/YOUR_USERNAME/repos-meetrhea/tower/hooks/tower-hook.sh"
          }
        ]
      }
    ]
  }
}
```

Replace `YOUR_USERNAME` with your actual username.

### Test the hook

```bash
# Start Tower in one terminal
python src/telegram_tower.py

# In another terminal, send a test event
echo '{"hook_event_name":"PermissionRequest","tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' | nc -U /tmp/tower.sock
```

You should see an instant Telegram notification with the ⚡ emoji.

### How it works

- **Without hooks**: Tower polls tmux every 2 seconds, then sends notification
- **With hooks**: Claude Code calls the hook script instantly on permission prompts

Both methods work together - hooks for instant permission detection, tmux polling for errors and STUCK detection.

---

## Next Steps

- **Voice messages**: Coming soon - send voice notes, Tower transcribes
- **Outbound alerts**: Tower messages you when agents need attention
- **Phone calls**: Full ATC experience (requires Twilio)

See [README.md](README.md) for commands and [PRD.md](PRD.md) for the full spec.

#!/bin/bash
# Tower Claude Code Hook
# This script is called by Claude Code on permission prompts and notifications.
# It sends event data to Tower via Unix socket for instant alerts.
#
# Installation:
#   Add to ~/.claude/settings.json:
#   {
#     "hooks": {
#       "PermissionRequest": [
#         {
#           "hooks": [
#             {
#               "type": "command",
#               "command": "/path/to/tower/hooks/tower-hook.sh"
#             }
#           ]
#         }
#       ],
#       "Notification": [
#         {
#           "matcher": "permission_prompt",
#           "hooks": [
#             {
#               "type": "command",
#               "command": "/path/to/tower/hooks/tower-hook.sh"
#             }
#           ]
#         }
#       ]
#     }
#   }

SOCKET_PATH="${TOWER_SOCKET:-/tmp/tower.sock}"

# Read JSON from stdin (Claude Code passes event data via stdin)
INPUT=$(cat)

# Add timestamp and send to Tower socket
EVENT_JSON=$(echo "$INPUT" | jq -c '. + {"tower_timestamp": now}' 2>/dev/null)

# If jq failed, wrap raw input
if [ -z "$EVENT_JSON" ]; then
    EVENT_JSON="{\"raw_input\": \"$(echo "$INPUT" | tr '\n' ' ' | sed 's/"/\\"/g')\", \"tower_timestamp\": $(date +%s)}"
fi

# Send to Tower socket (non-blocking, don't fail if Tower isn't running)
if [ -S "$SOCKET_PATH" ]; then
    echo "$EVENT_JSON" | nc -U -w 1 "$SOCKET_PATH" 2>/dev/null || true
fi

# Always exit 0 - we don't want to block Claude Code operations
exit 0

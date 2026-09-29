#!/bin/zsh
# Starts the family hub: a Claude Code session that answers iMessages, plus the
# morning digest. Run it on the hub's Mac user, in Terminal. Terminal holds the
# permissions the hub needs (Full Disk Access, Calendars, Reminders, and control
# of Messages), and everything started from here inherits them.
# Add this file to System Settings > General > Login Items so it starts at login.
# If Claude exits, it restarts after 10 seconds. Press Ctrl-C twice to stop.

cd "${0:A:h}"
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# The hub has its own contact, so no "Sent by Claude" footer on every reply.
export IMESSAGE_APPEND_SIGNATURE=false
# Read the allowlist (~/.claude/channels/imessage/access.json) once at start, so
# nothing that happens in a chat can change who is allowed to text the hub.
export IMESSAGE_ACCESS_MODE=static

# Morning digest, in the background. Its log is in ~/Library/Logs.
./hm digest-loop >> "$HOME/Library/Logs/family-hub-digest.log" 2>&1 &
DIGEST_PID=$!
trap 'kill $DIGEST_PID 2>/dev/null' EXIT
trap 'exit 0' INT TERM

while true; do
  # The first prompt makes Claude answer any texts sent while the hub was off.
  # hub-settings.json locks the session down: it may only run ./hm and reply.
  # The prompt goes before --channels, which takes every argument after it as a channel.
  claude "Run the startup check described in CLAUDE.md." \
    --settings hub-settings.json --channels plugin:imessage@claude-plugins-official
  echo "Claude exited at $(date). Restarting in 10 seconds (Ctrl-C to stop)..."
  sleep 10
done

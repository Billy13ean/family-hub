#!/bin/zsh
# Starts the family hub: a Claude Code session that answers iMessages, plus the
# morning digest. Run it on the hub's Mac user, in Terminal. Terminal holds the
# permissions the hub needs (Full Disk Access, Calendars, Reminders, and control
# of Messages), and everything started from here inherits them.
# Add this file to System Settings > General > Login Items so it starts at login.
# If Claude exits, it restarts after 10 seconds. Press Ctrl-C twice to stop.
# Claude is also restarted every night at 3 AM, so a long-running conversation
# doesn't keep growing and using more of the plan's limits with every text.

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
trap 'kill $DIGEST_PID $RESTART_PID 2>/dev/null' EXIT
trap 'exit 0' INT TERM

CHANNEL=plugin:imessage@claude-plugins-official
RESTART_HOUR=3

# Seconds from now until the next RESTART_HOUR:00 (macOS `date`).
seconds_until_restart() {
  local now target
  now=$(date +%s)
  target=$(date -v${RESTART_HOUR}H -v0M -v0S +%s)
  (( target <= now )) && target=$(date -v+1d -v${RESTART_HOUR}H -v0M -v0S +%s)
  echo $(( target - now ))
}

while true; do
  # Nightly restart: at RESTART_HOUR, stop this Claude session; the loop starts a fresh one.
  ( sleep $(seconds_until_restart) && pkill -TERM -f "channels $CHANNEL" ) &
  RESTART_PID=$!

  # The first prompt makes Claude answer any texts sent while the hub was off.
  # hub-settings.json locks the session down: it may only run ./hm and reply.
  # The prompt goes before --channels, which takes every argument after it as a channel.
  claude "Run the startup check described in CLAUDE.md." \
    --settings hub-settings.json --channels $CHANNEL

  kill $RESTART_PID 2>/dev/null  # Claude stopped early; cancel this session's restart timer
  echo "Claude exited at $(date). Restarting in 10 seconds (Ctrl-C to stop)..."
  sleep 10
done

#!/usr/bin/env bash
# Install the nightly backup job.
#
#   ./scripts/install_backup.sh
#
# Why it installs a COPY rather than pointing launchd at the repo:
# ~/Documents is protected by macOS TCC, and a launchd agent reading from
# there fails with "Operation not permitted" (exit 126) unless you grant
# Full Disk Access to /bin/bash -- far too broad a permission for this.
# ~/.local/bin is not TCC-protected, so the job just works.
#
# Re-run this after editing scripts/backup_db.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$HOME/.local/bin"
TARGET="$BIN_DIR/insite-backup.sh"
PLIST="$HOME/Library/LaunchAgents/com.insite.backup.plist"
LOG_DIR="$HOME/Insite-Backups"

mkdir -p "$BIN_DIR" "$LOG_DIR"
install -m 755 "$ROOT/scripts/backup_db.sh" "$TARGET"
echo "  installed $TARGET"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.insite.backup</string>
  <key>ProgramArguments</key>
  <array><string>$TARGET</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$LOG_DIR/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/launchd.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>DOCKER_BIN</key><string>$HOME/.docker/bin/docker</string>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
PLISTEOF
echo "  wrote $PLIST"

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "  loaded — runs daily at 02:00"
echo
echo "  verify now:   launchctl start com.insite.backup && sleep 5 && tail -3 $LOG_DIR/backup.log"
echo "  disable:      launchctl unload $PLIST"

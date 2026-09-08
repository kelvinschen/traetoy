#!/bin/bash
# Public actions go through Passport; backend actions are used by its lifecycle queue.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/macos-app/build/Passport.app"
BIN="$ROOT/rust-bridge/target/release/passport-bridge"
LABEL=cn.folotoy.codex-passport.bridge
DOMAIN="gui/$(id -u)"
TARGET="$DOMAIN/$LABEL"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
loaded() { launchctl print "$TARGET" >/dev/null 2>&1; }
pid() { launchctl print "$TARGET" 2>/dev/null | /usr/bin/awk '/^[[:space:]]*pid =/ {print $3}'; }
backend_stop() {
  local stop_started=$SECONDS
  if ! loaded; then return; fi
  if [ -n "$(pid)" ]; then
    "$BIN" --workspace "$ROOT" --control stop >/dev/null 2>&1 || launchctl kill SIGTERM "$TARGET" 2>/dev/null || true
  fi
  while (( SECONDS - stop_started < 40 )); do
    if [ -z "$(pid || true)" ]; then
      launchctl bootout "$TARGET" 2>/dev/null || true
      return 0
    fi
    sleep 0.5
  done
  echo '服务在 40 秒内未停止，请查看日志或使用菜单中的强制停止。' >&2
  return 1
}
case "${1:-status}" in
  install)
    test -x "$BIN" && test -x "$APP/Contents/MacOS/Passport"
    mkdir -p "$ROOT/backups" "$HOME/Library/LaunchAgents" "$ROOT/reports"
    if [ -f "$PLIST" ]; then cp -p "$PLIST" "$ROOT/backups/launchagent-before-tray-$(date +%Y%m%d%H%M%S).plist"; fi
    backend_stop
    TEMP="$(mktemp "$HOME/Library/LaunchAgents/.passport.XXXXXX")"
    trap 'rm -f "$TEMP"' EXIT
    plutil -create xml1 "$TEMP"
    plutil -insert Label -string "$LABEL" "$TEMP"
    plutil -insert ProgramArguments -array "$TEMP"
    plutil -insert ProgramArguments.0 -string "$BIN" "$TEMP"
    plutil -insert ProgramArguments.1 -string --workspace "$TEMP"
    plutil -insert ProgramArguments.2 -string "$ROOT" "$TEMP"
    plutil -insert ProgramArguments.3 -string --log-file "$TEMP"
    plutil -insert ProgramArguments.4 -string --managed "$TEMP"
    plutil -insert WorkingDirectory -string "$ROOT" "$TEMP"
    plutil -insert EnvironmentVariables -dictionary "$TEMP"
    plutil -insert EnvironmentVariables.HOME -string "$HOME" "$TEMP"
    plutil -insert EnvironmentVariables.PATH -string '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin' "$TEMP"
    plutil -insert RunAtLoad -bool NO "$TEMP"
    plutil -insert KeepAlive -bool NO "$TEMP"
    plutil -insert ExitTimeOut -integer 40 "$TEMP"
    plutil -insert StandardOutPath -string /dev/null "$TEMP"
    plutil -insert StandardErrorPath -string /dev/null "$TEMP"
    plutil -lint "$TEMP"
    mv "$TEMP" "$PLIST"
    launchctl enable "$TARGET"
    echo 'Installed; open Passport to start. Login startup is controlled in its menu.'
    ;;
  backend-start)
    test -f "$PLIST" || { echo 'Run bridge-service.sh install first.' >&2; exit 1; }
    plutil -extract ProgramArguments.4 raw "$PLIST" | /usr/bin/grep -qx -- --managed || { echo 'Legacy LaunchAgent: run install first.' >&2; exit 1; }
    launchctl enable "$TARGET"
    if ! loaded; then launchctl bootstrap "$DOMAIN" "$PLIST"; fi
    launchctl kickstart "$TARGET"
    ;;
  backend-stop) backend_stop ;;
  backend-force-stop)
    if loaded; then launchctl kill SIGKILL "$TARGET" 2>/dev/null || true; backend_stop; fi
    ;;
  start|restart|stop|quit|reconnect)
    if ! "$APP/Contents/MacOS/Passport" --workspace "$ROOT" --command "${1}"; then
      if [ "$1" = start ]; then open "$APP"; else exit 1; fi
    fi
    ;;
  status)
    "$APP/Contents/MacOS/Passport" --workspace "$ROOT" --command status || "$BIN" --workspace "$ROOT" --control status
    ;;
  uninstall)
    "$APP/Contents/MacOS/Passport" --workspace "$ROOT" --command quit || true
    backend_stop
    rm -f "$PLIST"
    echo 'LaunchAgent removed; workspace and pairing preserved. Disable login startup in System Settings if enabled.'
    ;;
  *) echo "Usage: $0 {install|start|stop|restart|quit|reconnect|status|uninstall}" >&2; exit 2 ;;
esac

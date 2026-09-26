#!/usr/bin/env bash
# Install and register the GitLab Runner that runs Insite's release and
# deploy jobs on this Mac.
#
#   1. GitLab: Settings -> CI/CD -> Runners -> New project runner
#      (tag insite-mac, "Run untagged jobs" OFF, "Protected" ON) -> Create.
#   2. Copy the runner token (glrt-...) it shows, then in a terminal:
#        pbpaste > ~/.config/insite/gitlab-runner-token && chmod 600 ~/.config/insite/gitlab-runner-token
#   3. ./scripts/install_runner.sh
#
# The runner uses the shell executor and runs as you, as a login LaunchAgent:
# `live.sh` needs your launchd domain, and jobs read the env files in
# ~/.config/insite. Builds go to ~/builds, outside ~/Documents (macOS blocks
# background agents from ~/Documents). Only protected refs (main, v* tags)
# reach it, so nobody else can run code on this machine.
set -euo pipefail

SECRETS="${INSITE_SECRETS_DIR:-$HOME/.config/insite}"
TOKEN_FILE="$SECRETS/gitlab-runner-token"
BIN="$HOME/.local/bin/gitlab-runner"
CONFIG="$HOME/.gitlab-runner/config.toml"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# --- binary (official build, checksum verified) ---------------------------
if [ ! -x "$BIN" ]; then
  arch="$(uname -m)"; [ "$arch" = x86_64 ] && arch=amd64
  base=https://s3.dualstack.us-east-1.amazonaws.com/gitlab-runner-downloads/latest
  tmp="$(mktemp -d)"
  curl -sSfLo "$tmp/runner" "$base/binaries/gitlab-runner-darwin-$arch"
  curl -sSfLo "$tmp/sums" "$base/release.sha256"
  want="$(grep "binaries/gitlab-runner-darwin-$arch$" "$tmp/sums" | awk '{print $1}')"
  got="$(shasum -a 256 "$tmp/runner" | awk '{print $1}')"
  [ -n "$want" ] && [ "$want" = "$got" ] || die "checksum mismatch for gitlab-runner"
  mkdir -p "$(dirname "$BIN")"
  install -m 755 "$tmp/runner" "$BIN"
  rm -rf "$tmp"
fi
"$BIN" --version | head -n 1

# --- registration ---------------------------------------------------------
if [ -f "$CONFIG" ] && grep -q 'url = "https://gitlab.com' "$CONFIG"; then
  echo "already registered ($CONFIG)"
else
  [ -s "$TOKEN_FILE" ] || die "no runner token in $TOKEN_FILE (see step 2 at the top of this script)"
  token="$(tr -d '[:space:]' < "$TOKEN_FILE")"
  case "$token" in glrt-*) ;; *) die "$TOKEN_FILE does not hold a glrt- runner token" ;; esac

  # Jobs get a login-free environment, so hand them the tools live.sh uses.
  tool_path=""
  for t in npm uv docker; do
    d="$(dirname "$(command -v "$t" || die "$t not found on PATH")")"
    case ":$tool_path:" in *":$d:"*) ;; *) tool_path="${tool_path:+$tool_path:}$d" ;; esac
  done

  "$BIN" register --non-interactive \
    --url https://gitlab.com \
    --token "$token" \
    --executor shell \
    --shell bash \
    --description "insite-mac ($(scutil --get LocalHostName 2>/dev/null || hostname))" \
    --builds-dir "$HOME/builds" \
    --cache-dir "$HOME/builds/.cache" \
    --env "PATH=$tool_path:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  # The token now lives in the runner's config (mode 600); drop the copy.
  rm -f "$TOKEN_FILE"
fi
chmod 600 "$CONFIG"

# --- service (user LaunchAgent, starts at login) -------------------------
if ! launchctl print "gui/$(id -u)/gitlab-runner" >/dev/null 2>&1; then
  (cd "$HOME" && "$BIN" install && "$BIN" start)
fi
sleep 2
"$BIN" verify 2>&1 | tail -n 3

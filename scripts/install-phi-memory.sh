#!/usr/bin/env bash
# Install Phi Memory as a user plugin for an existing Hermes Agent install.
#
# Curl usage:
#   curl -fsSL https://raw.githubusercontent.com/alienfrenZyNo1/hermes-agent/feature/phi-memory/scripts/install-phi-memory.sh | bash
#
# Options:
#   --force                 Replace an existing ~/.hermes/plugins/phi-memory directory
#   --no-enable             Install/copy but do not enable the plugin
#   --no-doctor             Skip post-install smoke checks
#   --repo URL              Git repo to clone from (default: alienfrenZyNo1/hermes-agent)
#   --ref REF               Git ref/branch/tag to clone (default: feature/phi-memory)
#   --subdir PATH           Plugin subdir inside repo (default: plugins/phi-memory)
#   --hermes-home PATH      Hermes data dir (default: $HERMES_HOME or ~/.hermes)
#   --source-dir PATH       Install from a local phi-memory plugin directory instead of git
#
# The script never edits MEMORY.md or USER.md. Enabling only updates Hermes config.yaml.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

REPO_URL="${PHI_MEMORY_REPO:-https://github.com/alienfrenZyNo1/hermes-agent.git}"
REF="${PHI_MEMORY_REF:-feature/phi-memory}"
SUBDIR="${PHI_MEMORY_SUBDIR:-plugins/phi-memory}"
HERMES_HOME_DIR="${HERMES_HOME:-$HOME/.hermes}"
FORCE=false
ENABLE=true
DOCTOR=true
SOURCE_DIR=""

log() { printf "%b\n" "$*"; }
info() { log "${BLUE}ℹ${NC} $*" >&2; }
success() { log "${GREEN}✓${NC} $*" >&2; }
warn() { log "${YELLOW}⚠${NC} $*" >&2; }
fatal() { log "${RED}✗${NC} $*" >&2; exit 1; }

usage() {
  sed -n '1,34p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force|-f)
      FORCE=true; shift ;;
    --no-enable)
      ENABLE=false; shift ;;
    --no-doctor)
      DOCTOR=false; shift ;;
    --repo)
      REPO_URL="${2:-}"; shift 2 ;;
    --ref|--branch)
      REF="${2:-}"; shift 2 ;;
    --subdir)
      SUBDIR="${2:-}"; shift 2 ;;
    --hermes-home)
      HERMES_HOME_DIR="${2:-}"; shift 2 ;;
    --source-dir)
      SOURCE_DIR="${2:-}"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      fatal "Unknown option: $1" ;;
  esac
done

[[ -n "$HERMES_HOME_DIR" ]] || fatal "Hermes home path is empty."
PLUGIN_NAME="phi-memory"
PLUGINS_DIR="$HERMES_HOME_DIR/plugins"
TARGET_DIR="$PLUGINS_DIR/$PLUGIN_NAME"

if ! command -v hermes >/dev/null 2>&1; then
  fatal "Hermes CLI was not found on PATH. Install Hermes first, then rerun this installer."
fi

mkdir -p "$PLUGINS_DIR"
TMP_DIR=""
cleanup() {
  if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

resolve_source() {
  if [[ -n "$SOURCE_DIR" ]]; then
    [[ -d "$SOURCE_DIR" ]] || fatal "--source-dir does not exist: $SOURCE_DIR"
    printf '%s\n' "$SOURCE_DIR"
    return
  fi

  command -v git >/dev/null 2>&1 || fatal "git is required to clone Phi Memory."
  TMP_DIR="$(mktemp -d)"
  info "Cloning $REPO_URL@$REF"
  git clone --depth 1 --branch "$REF" "$REPO_URL" "$TMP_DIR/repo" >/dev/null 2>&1 \
    || fatal "Could not clone $REPO_URL at ref '$REF'. Check the URL/ref or pass --repo/--ref."
  local src="$TMP_DIR/repo/$SUBDIR"
  [[ -d "$src" ]] || fatal "Plugin subdir not found in repo: $SUBDIR"
  printf '%s\n' "$src"
}

copy_plugin() {
  local src="$1"
  [[ -f "$src/plugin.yaml" ]] || fatal "Source does not look like a Hermes plugin: missing plugin.yaml in $src"
  if [[ -e "$TARGET_DIR" ]]; then
    if [[ "$FORCE" == true ]]; then
      local backup="$TARGET_DIR.bak.$(date +%Y%m%d%H%M%S)"
      info "Existing plugin found; moving it to $backup"
      mv "$TARGET_DIR" "$backup"
    else
      warn "Plugin already installed at $TARGET_DIR"
      warn "Leaving files unchanged. Use --force to replace them."
      return 0
    fi
  fi

  info "Installing Phi Memory to $TARGET_DIR"
  mkdir -p "$TARGET_DIR"
  # Copy contents without preserving local __pycache__ directories from development checkouts.
  (cd "$src" && tar --exclude='__pycache__' --exclude='*.pyc' -cf - .) | (cd "$TARGET_DIR" && tar -xf -)
  success "Plugin files installed."
}

enable_plugin() {
  if [[ "$ENABLE" != true ]]; then
    warn "Skipping enable step (--no-enable)."
    return 0
  fi
  info "Enabling Phi Memory in Hermes config"
  HERMES_HOME="$HERMES_HOME_DIR" hermes plugins enable "$PLUGIN_NAME"
}

run_doctor() {
  if [[ "$DOCTOR" != true ]]; then
    warn "Skipping doctor checks (--no-doctor)."
    return 0
  fi

  info "Running Phi Memory smoke check"
  if HERMES_HOME="$HERMES_HOME_DIR" hermes phi-memory status --target memory >/tmp/phi-memory-install-status.$$ 2>&1; then
    success "Phi Memory CLI smoke check passed."
    rm -f /tmp/phi-memory-install-status.$$
  else
    warn "Phi Memory CLI smoke check did not pass yet. Output:"
    sed 's/^/  /' /tmp/phi-memory-install-status.$$ || true
    rm -f /tmp/phi-memory-install-status.$$
    warn "If this is a running gateway/session, restart it so newly enabled plugins are discovered."
  fi

  info "Installed plugin status:"
  HERMES_HOME="$HERMES_HOME_DIR" hermes plugins list --user --plain || true
}

log ""
log "${GREEN}Phi Memory installer${NC}"
log "Hermes home: $HERMES_HOME_DIR"
log ""

SRC="$(resolve_source)"
copy_plugin "$SRC"
enable_plugin
run_doctor

log ""
success "Phi Memory install complete."
log "Try: hermes phi-memory status --target memory"
log "For gateways or long-running Hermes sessions, restart them to load the plugin."

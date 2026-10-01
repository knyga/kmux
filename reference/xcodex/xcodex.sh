# xcodex — run Codex against one of several isolated CODEX_HOME directories.
# The array slice is 0-based in both bash and zsh, so the public index stays 1-based.
XCODEX_DIRS=("$HOME/.codex" "$HOME/.codex-2" "$HOME/.codex-3" "$HOME/.codex-4")

# Codex owns these live values, so they stay current as the CLI evolves.
XCODEX_STATUS_ITEMS='["model-with-reasoning","git-branch","context-used","five-hour-limit","weekly-limit"]'

_xcodex_helper() {
  printf '%s\n' "$HOME/.config/xcodex/xcodex.py"
}

_xcodex_label() {
  local dir="$1" label
  if label=$(python3 "$(_xcodex_helper)" identity "$dir" 2>/dev/null); then
    printf '%s\n' "$label"
    return 0
  fi

  # File credentials are normal on Linux/WSL. This fallback also detects a
  # keyring-backed login without trying to read the keyring ourselves.
  if [ -d "$dir" ] && CODEX_HOME="$dir" command codex login status >/dev/null 2>&1; then
    printf '%s\n' "Codex account (keyring)"
    return 0
  fi
  return 1
}

_xcodex_list() {
  local i=1 d state label
  for d in "${XCODEX_DIRS[@]}"; do
    if [ -d "$d" ]; then state="exists"; else state="missing"; fi
    if label=$(_xcodex_label "$d"); then
      state="$state, logged in: $label"
    else
      state="$state, not logged in"
    fi
    printf '  %d) %s [%s]\n' "$i" "$d" "$state"
    i=$((i + 1))
  done
}

_xcodex_usage() {
  {
    echo "usage: xcodex <index> [codex args...]"
    echo "       xcodex ls"
    echo "       xcodex-seed <index>"
    _xcodex_list
  } >&2
}

# Echo the directory for a valid 1-based index, otherwise fail loudly.
_xcodex_dir() {
  case "${1-}" in '' | *[!0-9]*) _xcodex_usage; return 1 ;; esac
  if [ "$1" -lt 1 ] || [ "$1" -gt "${#XCODEX_DIRS[@]}" ]; then
    _xcodex_usage
    return 1
  fi
  printf '%s\n' "${XCODEX_DIRS[@]:$1-1:1}"
}

_xcodex_set_title() {
  [ -t 1 ] || return 0
  printf '\033]0;%s\007' "$1"
}

xcodex() {
  if [ "${1-}" = ls ]; then _xcodex_list; return 0; fi

  local index="${1-}" dir label title result title_set=0
  local -a injected
  dir=$(_xcodex_dir "$index") || return 1
  shift

  if [ ! -d "$dir" ]; then
    (umask 077; mkdir -p "$dir") || return 1
  fi

  if ! label=$(_xcodex_label "$dir"); then
    label="login required"
  fi
  title="xcodex $index · $label"

  injected=()
  if [ "${XCODEX_STATUS_LINE-1}" != 0 ]; then
    injected+=( -c "tui.status_line=$XCODEX_STATUS_ITEMS" )
  fi
  if [ "${XCODEX_TITLE-1}" != 0 ] && [ -t 1 ]; then
    # Keep Codex's native title updater from replacing the account identity.
    injected+=( -c 'tui.terminal_title=[]' )
    _xcodex_set_title "$title"
    title_set=1
  fi
  if [ "${XCODEX_ACCOUNT_BANNER-1}" != 0 ] && [ -t 2 ]; then
    printf 'xcodex: account %s · %s · %s\n' "$index" "$label" "$dir" >&2
  fi

  CODEX_HOME="$dir" command codex "${injected[@]}" "$@"
  result=$?

  if [ "$title_set" -eq 1 ]; then
    _xcodex_set_title ""
  fi
  return "$result"
}

# Copy only reusable configuration. Authentication, sessions, history, local
# databases, memories, caches, and MCP OAuth credentials are never candidates.
xcodex-seed() {
  local dst src="$HOME/.codex"
  dst=$(_xcodex_dir "${1-}") || return 1
  python3 "$(_xcodex_helper)" seed "$src" "$dst"
}

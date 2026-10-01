# xclaude — run Claude Code against one of several config dirs, chosen by index.
# Your shell is zsh; the slice below is 1-based-correct in zsh AND bash, so no off-by-one.
XCLAUDE_DIRS=("$HOME/.claude" "$HOME/.claude-2" "$HOME/.claude-3" "$HOME/.claude-4")

_xclaude_list() {
  local i=1 d state
  for d in "${XCLAUDE_DIRS[@]}"; do
    if [ -d "$d" ]; then state="exists"; else state="missing"; fi
    if [ -f "$d/.credentials.json" ] ||
       { [ "$(uname)" = Darwin ] &&
         security find-generic-password -s "Claude Code-credentials" >/dev/null 2>&1; }; then
      state="$state, logged in"
    fi
    printf '  %d) %s [%s]\n' "$i" "$d" "$state"
    i=$((i + 1))
  done
}

_xclaude_usage() {
  {
    echo "usage: xclaude <index> [claude args...]"
    echo "       xclaude ls"
    echo "       xclaude-seed <index>"
    _xclaude_list
  } >&2
}

# echoes the dir for a valid 1-based index, else prints usage and fails
_xclaude_dir() {
  case "$1" in '' | *[!0-9]*) _xclaude_usage; return 1 ;; esac
  if [ "$1" -lt 1 ] || [ "$1" -gt ${#XCLAUDE_DIRS[@]} ]; then _xclaude_usage; return 1; fi
  printf '%s\n' "${XCLAUDE_DIRS[@]:$1-1:1}"
}

# First-run bootstrap for a config dir that has no global config yet.
# Writes ONLY non-credential state: the answers to the first-run wizard, so
# `xclaude <n> --dangerously-skip-permissions` starts in bypass mode instead of
# stopping on the theme / onboarding / trust-folder / disclaimer prompts.
# Never touches an existing .claude.json. Logging in is still on you.
_xclaude_bootstrap() {
  local dir="$1" src="$HOME/.claude" trust="${XCLAUDE_TRUST_DIRS:-$PWD}"
  mkdir -p "$dir" || return 1
  [ -e "$dir/.claude.json" ] && return 0
  {
    printf '{\n'
    printf '  "hasCompletedOnboarding": true,\n'
    printf '  "bypassPermissionsModeAccepted": true,\n'
    printf '  "installMethod": "native",\n'
    printf '  "autoUpdates": false,\n'
    printf '  "projects": {\n'
    # one trusted path per line, so a path containing spaces survives
    printf '%s\n' "$trust" | awk 'NF { gsub(/\\/, "\\\\"); gsub(/"/, "\\\""); \
      if (n++) printf ",\n"; \
      printf "    \"%s\": { \"hasTrustDialogAccepted\": true, \"allowedTools\": [], \"mcpServers\": {} }", $0 }'
    printf '\n  }\n}\n'
  } > "$dir/.claude.json" || return 1
  # settings.json carries theme + skipDangerousModePermissionPrompt; copy it if absent.
  [ -e "$dir/settings.json" ] || { [ -f "$src/settings.json" ] && cp "$src/settings.json" "$dir/settings.json"; }
  return 0
}

xclaude() {
  if [ "$1" = ls ]; then _xclaude_list; return 0; fi
  local dir fresh=0; dir=$(_xclaude_dir "$1") || return 1
  shift
  [ -e "$dir/.claude.json" ] || fresh=1
  mkdir -p "$dir" || return 1
  _xclaude_bootstrap "$dir" || return 1
  [ $fresh -eq 1 ] && echo "xclaude: prepared $dir (log in when prompted)" >&2
  CLAUDE_CONFIG_DIR="$dir" command claude "$@"
}

# Copies shared config only. Never .credentials.json, never .claude.json.
xclaude-seed() {
  local dst src="$HOME/.claude" item reply
  dst=$(_xclaude_dir "$1") || return 1
  [ "$dst" = "$src" ] && { echo "xclaude-seed: $src is the source" >&2; return 1; }
  mkdir -p "$dst" || return 1
  _xclaude_bootstrap "$dst" || return 1
  for item in CLAUDE.md settings.json agents commands skills; do
    [ -e "$src/$item" ] || continue
    if [ -e "$dst/$item" ]; then
      printf 'overwrite %s? [y/N] ' "$dst/$item" >&2
      read -r reply || return 1
      case "$reply" in [yY]*) rm -rf "$dst/$item" ;; *) continue ;; esac
    fi
    cp -R "$src/$item" "$dst/$item"
  done
}

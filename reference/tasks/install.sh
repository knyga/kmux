#!/usr/bin/env bash
# Install the tasks/ kit (task store + tools/tasks CLI + skills + guard hook) into a git repository.
# Spec: docs/tasks.md in the kmux reference repo. Idempotent: a second run changes nothing.
#
#   install.sh [--dry-run] [<target-repo>]      # default target: the git toplevel of $PWD
#
# Kit-owned files (tools/tasks, tools/taskctl/*.py) are replaced when they differ, after a backup.
# Template files (tasks/*, skills) are created when absent and never overwritten: a project's own
# edits win. Shared files (.gitignore, AGENTS.md, CLAUDE.md, .claude/settings.json, .codex/hooks.json)
# are appended to / merged, after a backup. Nothing is committed; the caller commits with a pathspec.
set -euo pipefail

KIT="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)"
DRY=0
[ "${1:-}" = "--dry-run" ] && { DRY=1; shift; }
TARGET="${1:-$(git rev-parse --show-toplevel 2>/dev/null || true)}"
[ -n "$TARGET" ] || { echo "install: not inside a git repository; pass <target-repo>" >&2; exit 1; }
TARGET="$(cd -- "$TARGET" && pwd)"
git -C "$TARGET" rev-parse --git-dir >/dev/null 2>&1 || { echo "install: $TARGET is not a git repository" >&2; exit 1; }
[ "$(git -C "$TARGET" rev-parse --show-toplevel)" = "$TARGET" ] || {
  echo "install: $TARGET is not the repository root" >&2; exit 1; }
if [ "$(git -C "$TARGET" rev-parse --git-common-dir)" != "$(git -C "$TARGET" rev-parse --git-dir)" ]; then
  echo "install: $TARGET is a linked worktree; install into the main checkout" >&2; exit 1
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || {
  echo "install: python3 >= 3.11 is required (tools/taskctl uses datetime.UTC)" >&2; exit 1; }

# A project that already runs its own task store (another CLI) is not ours to overwrite.
if [ -f "$TARGET/tasks/README.md" ] && ! grep -q 'tools/tasks' "$TARGET/tasks/README.md"; then
  echo "install: $TARGET/tasks/README.md exists and is not this kit's contract (no 'tools/tasks')." >&2
  echo "         The project has its own task store; refusing to mix two. Nothing changed." >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$HOME/.config-backups/tasks-$STAMP"
CHANGED=() KEPT=() BACKED=() PATHS=()

say() { printf '%s\n' "$*"; }
backup() {  # backup <abs path>
  local f=$1 rel=${1#"$TARGET"/}
  [ -e "$f" ] || return 0
  [ $DRY = 1 ] && return 0
  mkdir -p "$BACKUP/$(dirname -- "$rel")"
  cp -p -- "$f" "$BACKUP/$rel"
  BACKED+=("$rel")
}
put() {  # put <kit rel src> <target rel dst> <mode> <owned|template>
  local src="$KIT/$1" dst="$TARGET/$2" mode=$3 kind=$4
  if [ -e "$dst" ]; then
    cmp -s -- "$src" "$dst" && return 0
    if [ "$kind" = template ]; then KEPT+=("$2"); return 0; fi
    backup "$dst"
  fi
  CHANGED+=("$2"); PATHS+=("$2")
  [ $DRY = 1 ] && return 0
  mkdir -p -- "$(dirname -- "$dst")"
  cp -- "$src" "$dst"
  chmod "$mode" "$dst"
}

# 1. the CLI (kit-owned)
put tools/tasks tools/tasks 755 owned
for f in "$KIT"/tools/taskctl/*.py; do
  put "tools/taskctl/$(basename -- "$f")" "tools/taskctl/$(basename -- "$f")" 644 owned
done

# 2. templates (created when absent, never overwritten)
while IFS= read -r rel; do
  put "template/$rel" "$rel" 644 template
done < <(cd "$KIT/template" && find . -type f | sed 's|^\./||' | sort)

# 3. .gitignore runtime state
GI="$TARGET/.gitignore"
missing=()
for line in "tasks/.leases/" "tasks/.claim.lock/" ".solve-loop/" ".worktrees/" "tools/taskctl/__pycache__/"; do
  grep -qxF -- "$line" "$GI" 2>/dev/null || missing+=("$line")
done
if [ ${#missing[@]} -gt 0 ]; then
  CHANGED+=(".gitignore (+${#missing[@]} lines)"); PATHS+=(".gitignore")
  if [ $DRY = 0 ]; then
    backup "$GI"
    { [ -s "$GI" ] && [ -n "$(tail -c1 "$GI")" ] && echo
      echo "# task tracker runtime state (tasks/ markdown files ARE committed)"
      printf '%s\n' "${missing[@]}"; } >> "$GI"
  fi
fi

# 4. guard hook: merge into .claude/settings.json and .codex/hooks.json (JSON, no jq needed)
merge_hook() {  # merge_hook <rel json> <command> <matcher>
  local rel=$1 cmd=$2 matcher=$3 f="$TARGET/$1"
  if [ -f "$f" ] && grep -qF 'tools/taskctl/guard.py' "$f"; then return 0; fi
  CHANGED+=("$rel (guard hook)"); PATHS+=("$rel")
  [ $DRY = 1 ] && return 0
  backup "$f"
  mkdir -p -- "$(dirname -- "$f")"
  python3 - "$f" "$cmd" "$matcher" <<'PY'
import json, sys, pathlib
path, cmd, matcher = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
data = json.loads(path.read_text()) if path.exists() and path.read_text().strip() else {}
hooks = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
entry = {"type": "command", "command": cmd, "timeout": 5}
if path.name == "hooks.json":
    entry["statusMessage"] = "Checking task workflow policy"
for group in hooks:
    if group.get("matcher") == matcher:
        group.setdefault("hooks", []).append(entry)
        break
else:
    hooks.append({"matcher": matcher, "hooks": [entry]})
path.write_text(json.dumps(data, indent=2) + "\n")
PY
}
merge_hook .claude/settings.json 'python3 "${CLAUDE_PROJECT_DIR}/tools/taskctl/guard.py"' 'Bash'
merge_hook .codex/hooks.json 'python3 "$(git rev-parse --show-toplevel)/tools/taskctl/guard.py"' '^Bash$'

# 5. agent entry points: the task-workflow section, once
MARK='<!-- tasks-kit:workflow -->'
SNIPPET="$KIT/snippets/task-workflow.md"
add_snippet() {  # add_snippet <rel md>
  local f="$TARGET/$1"
  if [ -f "$f" ] && grep -qF -- "$MARK" "$f"; then return 0; fi
  CHANGED+=("$1 (task workflow section)"); PATHS+=("$1")
  [ $DRY = 1 ] && return 0
  backup "$f"
  { [ -s "$f" ] && echo; cat "$SNIPPET"; } >> "$f"
}
add_snippet AGENTS.md
if [ -f "$TARGET/CLAUDE.md" ]; then
  grep -qE '^@AGENTS\.md' "$TARGET/CLAUDE.md" || add_snippet CLAUDE.md
else
  CHANGED+=("CLAUDE.md (new: @AGENTS.md import)"); PATHS+=("CLAUDE.md")
  [ $DRY = 0 ] && printf '@AGENTS.md\n' > "$TARGET/CLAUDE.md"
fi

# 6. backup manifest + report
if [ ${#BACKED[@]} -gt 0 ]; then
  { echo "tasks kit install into $TARGET at $STAMP"
    echo "backed up (copies of the files as they were before this run):"
    printf '  %s\n' "${BACKED[@]}"
    echo "created (absent before, nothing to back up):"
    for c in "${CHANGED[@]}"; do
      p=${c%% (*}; printf '%s\n' "${BACKED[@]}" | grep -qxF -- "$p" || printf '  %s\n' "$c"
    done; } > "$BACKUP/MANIFEST.txt"
fi

[ $DRY = 1 ] && say "DRY RUN — nothing written. Would change:" || say "tasks kit installed into $TARGET"
if [ ${#CHANGED[@]} -eq 0 ]; then say "  nothing to change (already installed)"; else printf '  + %s\n' "${CHANGED[@]}"; fi
[ ${#KEPT[@]} -gt 0 ] && { say "kept the project's own version (differs from the kit):"; printf '  = %s\n' "${KEPT[@]}"; }
[ ${#BACKED[@]} -gt 0 ] && say "backup: $BACKUP (MANIFEST.txt)"
if [ $DRY = 0 ] && [ ${#CHANGED[@]} -gt 0 ]; then
  mapfile -t ADD < <(printf '%s\n' "${PATHS[@]}" | sed -E 's#^(tools/taskctl|tasks)/.*#\1#; s#^(\.claude/skills|\.agents/skills)/([^/]+)/.*#\1/\2#' | sort -u)
  say ""
  say "next: put the project's real lint/test commands in tasks/gate.cmds, then commit the kit on main:"
  say "  cd $TARGET && git add -- ${ADD[*]}"
  say "  git commit -m 'tasks: install the task queue kit' -- ${ADD[*]}"
  say "(claim makes worktrees from main: until the kit is committed there, a worktree has no tools/tasks)"
fi

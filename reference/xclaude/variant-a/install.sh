#!/usr/bin/env bash
# Install / re-install xclaude on this machine.
#
# The unit of replication is this whole directory. Copy ~/.config/xclaude to the
# new machine (scp, git, dotfiles repo -- anything), then run ./install.sh.
# It is idempotent: safe to re-run after an upgrade or a fresh clone.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
statusline="$here/statusline.py"

command -v python3 >/dev/null || { echo "xclaude: python3 is required" >&2; exit 1; }
[ -f "$here/xclaude.sh" ] || { echo "xclaude: xclaude.sh missing from $here" >&2; exit 1; }
[ -f "$statusline" ]      || { echo "xclaude: statusline.py missing from $here" >&2; exit 1; }
chmod +x "$statusline" "$here/install.sh"

# 1. read the config-dir list from the single source of truth: xclaude.sh
#    (sourced in a subshell so this installer never leaks the functions)
dirs=$( . "$here/xclaude.sh"; printf '%s\n' "${XCLAUDE_DIRS[@]}" )

# 2. make sure interactive shells pick up the xclaude/xclaude-seed functions
line=". \"\$HOME/.config/xclaude/xclaude.sh\""
for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
  [ -f "$rc" ] || continue
  if grep -qF 'xclaude/xclaude.sh' "$rc"; then
    echo "xclaude: $rc already sources xclaude.sh"
  else
    printf '\n[ -f "$HOME/.config/xclaude/xclaude.sh" ] && %s\n' "$line" >> "$rc"
    echo "xclaude: appended source line to $rc"
  fi
done

# 3. install the status line into every config dir's settings.json
#    (XCLAUDE_STATUSLINE=0 skips this step: xclaude without the status bar)
while IFS= read -r d; do
  [ -n "$d" ] || continue
  mkdir -p "$d"
  [ "${XCLAUDE_STATUSLINE:-1}" = 0 ] && continue
  STATUSLINE="$statusline" SETTINGS="$d/settings.json" python3 - <<'PY'
import json, os
settings, statusline = os.environ["SETTINGS"], os.environ["STATUSLINE"]
try:
    with open(settings) as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("settings.json is not an object")
except FileNotFoundError:
    data = {}
data["statusLine"] = {"type": "command", "command": statusline, "padding": 0}
tmp = settings + ".tmp"
with open(tmp, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
os.replace(tmp, settings)
print(f"xclaude: statusLine installed in {settings}")
PY
done <<< "$dirs"

echo
echo "Done. Open a new shell (or 'exec \$SHELL'), then:"
echo "  xclaude ls        # list the config dirs and their login state"
echo "  xclaude 2         # run Claude Code as the second account"

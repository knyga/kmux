#!/usr/bin/env bash
# Install or re-install xcodex on this machine. Idempotent and credential-safe.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

command -v python3 >/dev/null || { echo "xcodex: python3 is required" >&2; exit 1; }
command -v codex >/dev/null || { echo "xcodex: codex is required" >&2; exit 1; }
[ -f "$here/xcodex.sh" ] || { echo "xcodex: xcodex.sh missing from $here" >&2; exit 1; }
[ -f "$here/xcodex.py" ] || { echo "xcodex: xcodex.py missing from $here" >&2; exit 1; }
chmod +x "$here/install.sh" "$here/xcodex.py"

# Read the account directory list from its single source of truth without
# leaking any functions into the installer's shell.
dirs=$( . "$here/xcodex.sh"; printf '%s\n' "${XCODEX_DIRS[@]}" )

line='. "$HOME/.config/xcodex/xcodex.sh"'
for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
  [ -f "$rc" ] || continue
  if grep -qF 'xcodex/xcodex.sh' "$rc"; then
    echo "xcodex: $rc already sources xcodex.sh"
  else
    printf '\n[ -f "$HOME/.config/xcodex/xcodex.sh" ] && %s\n' "$line" >> "$rc"
    echo "xcodex: appended source line to $rc"
  fi
done

while IFS= read -r directory; do
  [ -n "$directory" ] || continue
  if [ ! -d "$directory" ]; then
    (umask 077; mkdir -p "$directory")
    echo "xcodex: created $directory"
  fi
done <<< "$dirs"

echo
echo "Done. Open a new shell (or source xcodex.sh), then:"
echo "  xcodex ls        # list isolated Codex homes and login state"
echo "  xcodex 2         # log in and run Codex as the second account"
echo "  xcodex-seed 2    # optionally copy shared configuration"

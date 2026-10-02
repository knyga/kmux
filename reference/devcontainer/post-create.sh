#!/usr/bin/env bash
# Runs once after the container is created (and after every rebuild). Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."

# Named volumes are created root-owned; hand them to the dev user.
for d in "$HOME/.claude" "$HOME/.claude-2" "$HOME/.codex" "$HOME/.codex-2" \
         "$HOME/.config/gh" "$HOME/.local/share/tmux"; do
  sudo mkdir -p "$d"
  sudo chown -R "$(id -u):$(id -g)" "$d"
done

git config --global --add safe.directory "$PWD"

# Home tools from the kmux kit (kmux, xclaude, xcodex, status bars): the $HOME layer is new on
# every rebuild, so reinstall them here. KIT_COMPONENTS comes from devcontainer.json.
if [ -n "${KIT_COMPONENTS// /}" ]; then
  kit="${KIT_DIR:-$HOME/.local/share/kmux-kit}"
  if [ ! -d "$kit/.git" ]; then
    git clone -q --depth 1 "${KIT_REPO:-https://github.com/knyga/kmux.git}" "$kit"
  else
    git -C "$kit" pull -q --ff-only || echo "post-create: kit pull failed; using the existing checkout"
  fi
  bash "$kit/reference/devcontainer/kit-bootstrap.sh" "$kit"
fi

# --- Project dependencies -------------------------------------------------------------------
# Fill in for the project's stack, e.g.:
#   [ -f package-lock.json ] && npm ci
#   [ -f pyproject.toml ] && uv sync --dev

mkdir -p .secrets   # git-ignored; project-scoped credentials only

echo "==> Verifying outbound network (no firewall is installed by design)"
for url in https://api.anthropic.com https://api.openai.com https://github.com https://pypi.org https://registry.npmjs.org; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url" || true)
  printf '    %-32s %s\n' "$url" "${code:-000}"
done
echo "    (any HTTP status = reachable; 000 = blocked)"

echo
echo "Dev container ready."
echo "  claude : $(claude --version 2>/dev/null || echo 'not found')   (log in: claude, then /login)"
echo "  codex  : $(codex --version 2>/dev/null || echo 'not found')   (log in: codex login)"
echo "  kit    : ${KIT_COMPONENTS:-none}   (new shell: exec zsh; then kmux / xclaude ls / xcodex ls)"

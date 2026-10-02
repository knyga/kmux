#!/usr/bin/env bash
# Non-interactive install of the kit's home tools, for postCreateCommand (a rebuilt container has
# a fresh $HOME layer). The interactive equivalent is AGENTS.md; this script is its unattended form.
#
#   KIT_COMPONENTS="kmux xclaude claude-statusline xcodex codex-statusline vim nvim" kit-bootstrap.sh <kit-dir>
#
# Components (space separated, any subset): kmux xclaude claude-statusline xcodex codex-statusline
# vim nvim. Editors are installed bare: an existing ~/.vimrc, ~/.vim or ~/.config/nvim is never touched.
# Idempotent. Backs up every file it changes into ~/.config-backups/kit-bootstrap-<UTC>/ with a
# MANIFEST.txt. Never reads, copies or logs a credential file.
set -euo pipefail

kit=$(cd "${1:?usage: kit-bootstrap.sh <kit-dir>}" && pwd)
components=" ${KIT_COMPONENTS-} "
want() { [[ "$components" == *" $1 "* ]]; }
log() { printf 'kit-bootstrap: %s\n' "$*"; }

for c in ${KIT_COMPONENTS-}; do
  case "$c" in kmux|xclaude|claude-statusline|xcodex|codex-statusline|vim|nvim) ;;
    *) log "unknown component '$c' (dch, tasks and devcontainer are not home-tool components)" >&2; exit 64 ;;
  esac
done
[ -n "${KIT_COMPONENTS// /}" ] || { log "KIT_COMPONENTS is empty; nothing to do"; exit 0; }

backup="$HOME/.config-backups/kit-bootstrap-$(date -u +%Y%m%dT%H%M%SZ)"
[ -e "$backup" ] && backup="$backup-$$"  # two runs in the same second never share a backup
mkdir -p "$backup"
manifest="$backup/MANIFEST.txt"
backup_path() {  # copy an existing path into the backup dir, or record it as absent
  local p="$1"
  grep -qxF "$p" "$manifest.paths" 2>/dev/null && return 0
  echo "$p" >> "$manifest.paths"
  if [ -e "$p" ]; then
    mkdir -p "$backup$(dirname "$p")"
    cp -a "$p" "$backup$p"
    echo "backed up: $p" >> "$manifest"
  else
    echo "absent:    $p" >> "$manifest"
  fi
}
rc_line() {  # append a line to every existing rc file unless the marker is already there
  local marker="$1" line="$2" rc
  for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [ -f "$rc" ] || continue
    grep -qF "$marker" "$rc" && continue
    backup_path "$rc"
    printf '\n%s\n' "$line" >> "$rc"
    log "appended to $rc: $line"
  done
}

if want kmux; then
  backup_path "$HOME/bin/kmux"; backup_path "$HOME/.local/bin/kmux"; backup_path "$HOME/.tmux.conf"
  mkdir -p "$HOME/bin" "$HOME/.local/bin"
  install -m 755 "$kit/reference/kmux/variant-a/kmux" "$HOME/bin/kmux"
  ln -sfn "$HOME/bin/kmux" "$HOME/.local/bin/kmux"
  cp "$kit/reference/kmux/variant-a/tmux.conf" "$HOME/.tmux.conf"
  # Clone every @plugin from tmux.conf directly. (tpm's install_plugins asks the *default* tmux
  # server for the plugin list, which is not the new config and may be the user's live server.)
  for plugin in $(sed -n "s/^set -g @plugin '\([^']*\)'.*/\1/p" "$HOME/.tmux.conf"); do
    dest="$HOME/.tmux/plugins/${plugin##*/}"
    [ -d "$dest" ] || git clone -q --depth 1 "https://github.com/$plugin" "$dest" \
      || log "warning: could not clone $plugin; run prefix+I inside tmux"
  done
  log "kmux installed ($(tmux -V))"
fi

xclaude_dir="$HOME/.config/xclaude"
if want xclaude || want claude-statusline; then
  backup_path "$xclaude_dir"
  mkdir -p "$xclaude_dir"
  cp "$kit/reference/xclaude/variant-a/statusline.py" "$xclaude_dir/"
  chmod +x "$xclaude_dir/statusline.py"
fi
if want xclaude; then
  cp "$kit/reference/xclaude/variant-a/"{xclaude.sh,install.sh,README.md} "$xclaude_dir/"
  for d in $( . "$xclaude_dir/xclaude.sh"; printf '%s\n' "${XCLAUDE_DIRS[@]}" ); do
    backup_path "$d/settings.json"
  done
  for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do [ -f "$rc" ] && backup_path "$rc"; done
  if want claude-statusline; then
    bash "$xclaude_dir/install.sh"
  else
    XCLAUDE_STATUSLINE=0 bash "$xclaude_dir/install.sh"
  fi
elif want claude-statusline; then
  # Status line alone: wire it into the default profile only.
  settings="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
  backup_path "$settings"
  mkdir -p "$(dirname "$settings")"
  STATUSLINE="$xclaude_dir/statusline.py" SETTINGS="$settings" python3 - <<'PY'
import json, os
settings, statusline = os.environ["SETTINGS"], os.environ["STATUSLINE"]
try:
    with open(settings) as fh:
        data = json.load(fh)
except FileNotFoundError:
    data = {}
data["statusLine"] = {"type": "command", "command": statusline, "padding": 0}
with open(settings + ".tmp", "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
os.replace(settings + ".tmp", settings)
print(f"kit-bootstrap: statusLine installed in {settings}")
PY
fi

xcodex_dir="$HOME/.config/xcodex"
if want xcodex; then
  command -v codex >/dev/null || { log "xcodex needs codex on PATH" >&2; exit 1; }
  backup_path "$xcodex_dir"
  for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do [ -f "$rc" ] && backup_path "$rc"; done
  mkdir -p "$xcodex_dir"
  cp "$kit/reference/xcodex/"{xcodex.sh,xcodex.py,install.sh,README.md} "$xcodex_dir/"
  bash "$xcodex_dir/install.sh"
  # xcodex injects the status line per run; XCODEX_STATUS_LINE=0 turns that off.
  want codex-statusline || rc_line 'XCODEX_STATUS_LINE=0' 'export XCODEX_STATUS_LINE=0  # kit: no Codex status bar'
elif want codex-statusline; then
  # Status line alone: write it into the default CODEX_HOME's config.toml, unless one is set.
  config="${CODEX_HOME:-$HOME/.codex}/config.toml"
  backup_path "$config"
  mkdir -p "$(dirname "$config")"
  CONFIG="$config" python3 - <<'PY'
import os, re, tomllib
path = os.environ["CONFIG"]
items = '["model-with-reasoning","git-branch","context-used","five-hour-limit","weekly-limit"]'
text = open(path).read() if os.path.exists(path) else ""
if "status_line" in tomllib.loads(text).get("tui", {}):
    print(f"kit-bootstrap: {path} already sets tui.status_line; left alone")
else:
    m = re.search(r"(?m)^\[tui\][ \t]*$", text)
    if m:
        text = text[: m.end()] + f"\nstatus_line = {items}" + text[m.end():]
    else:
        sep = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
        text = text + sep + f"[tui]\nstatus_line = {items}\n"
    tomllib.loads(text)  # refuse to write a file Codex could not parse
    with open(path + ".tmp", "w") as fh:
        fh.write(text)
    os.replace(path + ".tmp", path)
    print(f"kit-bootstrap: tui.status_line installed in {path}")
PY
fi

failed=""

if want vim; then
  if command -v vim >/dev/null; then
    log "vim already installed ($(vim --version | head -1))"
  else
    if [ "$(id -u)" = 0 ]; then as_root=(); else as_root=(sudo -n); fi
    if command -v apt-get >/dev/null; then
      "${as_root[@]}" apt-get update -qq && "${as_root[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends vim
    elif command -v dnf >/dev/null; then "${as_root[@]}" dnf install -y -q vim-enhanced
    elif command -v apk >/dev/null; then "${as_root[@]}" apk add -q vim
    elif command -v brew >/dev/null; then brew install -q vim
    else false
    fi && log "vim installed ($(vim --version | head -1))" \
       || { log "warning: could not install vim (no package manager, or sudo needs a password)" >&2; failed="$failed vim"; }
  fi
fi

if want nvim; then
  # Official release tarball: distro packages lag far behind (Debian bookworm ships 0.7).
  # NVIM_VERSION pins a tag (e.g. v0.11.4); default "stable". An existing install is kept unless
  # NVIM_VERSION names a different version.
  nvim_root="$HOME/.local/opt/nvim"
  have=$("$nvim_root/bin/nvim" --version 2>/dev/null | head -1 | awk '{print $2}' || true)
  if [ -n "$have" ] && { [ -z "${NVIM_VERSION-}" ] || [ "${NVIM_VERSION}" = "$have" ]; }; then
    log "nvim already installed ($have)"
  else
    case "$(uname -s)-$(uname -m)" in
      Linux-x86_64)               asset=nvim-linux-x86_64 ;;
      Linux-aarch64|Linux-arm64)  asset=nvim-linux-arm64 ;;
      Darwin-arm64)               asset=nvim-macos-arm64 ;;
      Darwin-x86_64)              asset=nvim-macos-x86_64 ;;
      *) asset="" ;;
    esac
    tmp=$(mktemp -d)
    if [ -n "$asset" ] \
       && curl -fsSL "https://github.com/neovim/neovim/releases/download/${NVIM_VERSION:-stable}/$asset.tar.gz" \
            | tar -xz -C "$tmp" \
       && "$tmp/$asset/bin/nvim" --version >/dev/null; then
      mkdir -p "$HOME/.local/opt" "$HOME/.local/bin"
      rm -rf "$nvim_root"; mv "$tmp/$asset" "$nvim_root"
      ln -sfn "$nvim_root/bin/nvim" "$HOME/.local/bin/nvim"
      log "nvim installed ($("$nvim_root/bin/nvim" --version | head -1)) at $nvim_root"
    else
      log "warning: could not install nvim for $(uname -s)-$(uname -m)" >&2; failed="$failed nvim"
    fi
    rm -rf "$tmp"
  fi
fi

rm -f "$manifest.paths"
log "done; backups and MANIFEST.txt in $backup"
[ -z "$failed" ] || { log "FAILED:$failed" >&2; exit 1; }

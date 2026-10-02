# vim and nvim — build spec

Two optional menu items (AGENTS.md step 0, items 6 and 7): a terminal editor for working inside
kmux sessions and devcontainers, where no GUI editor is attached. They install the **editor only**.
No config, plugins or plugin manager are shipped, and an existing `~/.vimrc`, `~/.vim/` or
`~/.config/nvim/` is never created, overwritten, moved or "improved".

| Item | Source | Installed at | Why this source |
|---|---|---|---|
| `vim` | the distro package (`apt-get install vim`, `dnf install vim-enhanced`, `apk add vim`, `brew install vim`) | system `PATH` | Distro vim is current enough and gets security updates with the OS |
| `nvim` | official release tarball, `github.com/neovim/neovim/releases/download/<tag>/nvim-<os>-<arch>.tar.gz` | `~/.local/opt/nvim/`, symlink `~/.local/bin/nvim` | Distro packages lag badly (Debian bookworm: 0.7), and most current plugins need ≥ 0.10. No sudo needed |

Unattended implementation: `reference/devcontainer/kit-bootstrap.sh` (`KIT_COMPONENTS="… vim nvim"`).
On a host, an agent may run it directly: `KIT_COMPONENTS="vim nvim" reference/devcontainer/kit-bootstrap.sh .`

## 1. Install

1. **vim**: skip if `command -v vim` resolves. On Debian/Ubuntu `vim-tiny` provides only `vi` and
   `vim.tiny`, so a bare `vim` lookup is the right test. Otherwise install the package with the
   package manager found (`sudo -n`, so a password prompt fails fast instead of hanging an
   unattended run; report it and let the user run it). In a devcontainer you may instead add `vim`
   to the Dockerfile's `apt-get install` list, which is what the source projects did; then leave
   `vim` out of `KIT_COMPONENTS`.
2. **nvim**: map `uname -s`-`uname -m` to the asset (`Linux-x86_64` → `nvim-linux-x86_64`,
   `Linux-aarch64` → `nvim-linux-arm64`, `Darwin-arm64` → `nvim-macos-arm64`, `Darwin-x86_64` →
   `nvim-macos-x86_64`). Download `stable` (or the tag in `NVIM_VERSION`, e.g. `v0.11.4`), extract
   to a temp dir, run `nvim --version` from there, and only then replace `~/.local/opt/nvim` and
   `ln -sfn` the symlink. An existing install is kept unless `NVIM_VERSION` names another version.
3. `~/.local/bin` must be on `PATH` (the devcontainer Dockerfile sets it; on a host see
   [kmux.md](kmux.md) § 5 step 4).
4. Don't set `EDITOR`/`VISUAL`/`git core.editor` unless the user asks.

## 2. Verification checklist

| # | Check | Expectation |
|---|---|---|
| 1 | vim | `vim --version \| head -1` → `VIM - Vi IMproved 9.x …` (not "Small version" / tiny) |
| 2 | nvim | `nvim --version \| head -1` → `NVIM v0.1x…`; `readlink -f "$(command -v nvim)"` is under `~/.local/opt/nvim` |
| 3 | nvim runs headless | `nvim --headless +q; echo $?` → `0` |
| 4 | Idempotent | a second run prints `already installed` for both and changes nothing |
| 5 | Configs untouched | `ls -la ~/.vimrc ~/.vim ~/.config/nvim` shows the same result as before the install |

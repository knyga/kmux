# Prompt: rebuild `kmux` in a fresh environment

Set up `kmux` on this machine: a one-word command that drops me into a persistent
tmux session running Claude Code, with exactly one session per repository.

## What kmux must do (behavior contract)

`kmux` takes no arguments. Any argument is a usage error on stderr, exit code 64.

1. Resolve the target directory: `git rev-parse --show-toplevel`, falling back to
   `pwd -P` outside a repo. Canonicalize it (resolve symlinks).
2. Derive a stable session name from that absolute path:
   `kmux_<sanitized basename>_<first 10 chars of `git hash-object --stdin` over the path>`.
   Sanitize by squeezing every run of characters outside `[:alnum:]_-` to a single `_`
   (`LC_ALL=C tr -cs`), then trimming leading/trailing `_`; if nothing survives, use
   `directory`. The hash suffix is what keeps two same-named repos in different
   parents from colliding, so the name must depend on the full path, not the basename.
3. If run **outside** tmux: `tmux new-session -A` on that name with `-c <repo>` running
   `exec claude` — attach if it already exists, create it if not.
4. If run **inside** tmux (`$TMUX` set): never nest. Create the session detached only
   if `tmux has-session -t "=$session"` says it is missing, then
   `exec tmux switch-client -t "=$session"`.
5. Use the `=` exact-match prefix on every target so a prefix of another session name
   can never be matched by accident.
6. `set -euo pipefail`, and `exec` the final tmux call so no wrapper shell lingers.

Reference implementation to install verbatim at `~/bin/kmux` (mode 755), with
`~/.local/bin/kmux` as a symlink to it:

```bash
#!/usr/bin/env bash
set -euo pipefail

if (( $# != 0 )); then
  printf 'Usage: kmux\n' >&2
  exit 64
fi

repo=$(git rev-parse --show-toplevel 2>/dev/null || pwd -P)
repo=$(cd -- "$repo" && pwd -P)
repo_name=$(basename -- "$repo")
safe_name=$(printf '%s' "$repo_name" | LC_ALL=C tr -cs '[:alnum:]_-' '_')
safe_name=${safe_name#_}
safe_name=${safe_name%_}
if [[ -z "$safe_name" ]]; then
  safe_name=directory
fi

path_hash=$(printf '%s' "$repo" | git hash-object --stdin | cut -c1-10)
session="kmux_${safe_name}_${path_hash}"

if [[ -n ${TMUX:-} ]]; then
  if ! tmux has-session -t "=$session" 2>/dev/null; then
    tmux new-session -d -s "$session" -c "$repo" 'exec claude'
  fi
  exec tmux switch-client -t "=$session"
fi

exec tmux new-session -A -s "$session" -c "$repo" 'exec claude'
```

## Prerequisites to verify or install

- **tmux >= 3.2** (`set -as terminal-features` and `set-clipboard` need it; 3.5a is what
  this config was written against). If the distro package is older, install a newer
  build into `~/.local/bin/tmux` rather than fighting the system package.
- `git` on PATH — kmux uses `git hash-object` for the session hash, not just for repo
  detection, so it is required even outside a repo.
- `claude` resolvable on PATH from a **non-interactive** shell: the session command is
  `exec claude`, so a PATH entry that only exists in an interactive rc file will make
  every kmux session die instantly. Confirm with `env -i PATH="$PATH" claude --version`.
- `~/bin` and `~/.local/bin` on PATH. On a Debian-ish box the stock `~/.profile`
  already prepends both when they exist — but it tests for existence at login, so a
  directory created after login needs a re-login or a manual `export`.

## tmux configuration

Install this at `~/.tmux.conf`:

```tmux
# Terminal capabilities
set -g default-terminal 'tmux-256color'
set -as terminal-features ',xterm*:RGB,screen*:RGB,tmux*:RGB'
set -as terminal-features ',xterm*:clipboard'
set -s set-clipboard on

# General behavior
set -g mouse on
set -g history-limit 100000
setw -g mode-keys vi
setw -g aggressive-resize on

# Top status bar with visible current-window and activity states
set -g status on
set -g status-position top
set -g status-interval 15
set -g status-style 'fg=colour250,bg=colour234'
set -g status-left '#[fg=colour81,bold] #S #[default]'
set -g status-right '#{continuum_status} #[fg=colour245]%Y-%m-%d %H:%M '
set -g window-status-separator ''
set -g window-status-style 'fg=colour245,bg=colour234'
set -g window-status-format ' #{?window_activity_flag,!, }#I:#W '
set -g window-status-current-style 'fg=colour232,bg=colour81,bold'
set -g window-status-current-format ' #I:#W#{?window_zoomed_flag, [Z],} '
set -g window-status-activity-style 'fg=colour226,bg=colour234,bold'
setw -g monitor-activity on
set -g visual-activity off

# Direct window selection and cycling
bind-key -n M-1 select-window -t :1
bind-key -n M-2 select-window -t :2
bind-key -n M-3 select-window -t :3
bind-key -n M-4 select-window -t :4
bind-key -n M-5 select-window -t :5
bind-key -n M-6 select-window -t :6
bind-key -n M-7 select-window -t :7
bind-key -n M-8 select-window -t :8
bind-key -n M-9 select-window -t :9
bind-key -n M-0 select-window -t :0
bind-key -n M-Left previous-window
bind-key -n M-Right next-window

# Splits, panes, copy mode, zoom, and reload
bind-key '|' split-window -h -c '#{pane_current_path}'
bind-key '-' split-window -v -c '#{pane_current_path}'
bind-key h select-pane -L
bind-key j select-pane -D
bind-key k select-pane -U
bind-key l select-pane -R
bind-key H resize-pane -L 5
bind-key J resize-pane -D 5
bind-key K resize-pane -U 5
bind-key L resize-pane -R 5
bind-key z resize-pane -Z
bind-key Enter copy-mode
bind-key r source-file ~/.tmux.conf \; display-message 'tmux configuration reloaded'

# Session persistence. Keep Continuum last so its status hook remains active.
set -g @plugin 'tmux-plugins/tpm'
set -g @plugin 'tmux-plugins/tmux-resurrect'
set -g @plugin 'tmux-plugins/tmux-continuum'
set -g @continuum-save-interval '5'
set -g @continuum-restore 'on'
set -g @resurrect-capture-pane-contents 'on'

run-shell '~/.tmux/plugins/tpm/tpm'
```

Then install the plugins:

```
git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
~/.tmux/plugins/tpm/bin/install_plugins   # or prefix+I from inside tmux
```

Expected result: `~/.tmux/plugins/` holds `tpm`, `tmux-resurrect`, `tmux-continuum`.
Continuum's `run-shell` line must stay last in the file — it registers the status-right
hook that drives the autosave timer, and an earlier `run-shell` gets overwritten.
`#{continuum_status}` in `status-right` is what makes the autosave state visible; if
you drop it, autosave still runs but silently.

## Procedure

1. **Back up first.** Copy every file you are about to touch into
   `~/.config-backups/kmux-<UTC timestamp, e.g. 20260829T183952Z>/` together with a
   `MANIFEST.txt` that lists, per file, its original absolute path — and explicitly
   names the paths that did *not* exist before, so the change is exactly reversible.
   Candidates: `~/.bashrc`, `~/.profile`, `~/.zshrc`, `~/.tmux.conf`, `~/bin`.
2. Install the prerequisites that are missing.
3. Write `~/bin/kmux`, `chmod 755`, symlink `~/.local/bin/kmux -> ~/bin/kmux`.
4. Write `~/.tmux.conf`, clone tpm, install plugins.
5. Run the acceptance checks below and show me the output.
6. Report what you changed and how to roll it back.

## Acceptance checks — run these, don't assume

- `kmux extra-arg` prints `Usage: kmux` to stderr and exits 64.
- From two different repos, kmux yields two different session names; from the same repo
  twice, the same name (`tmux ls` proves it — the second call attaches, never creates).
- Two repos sharing a basename under different parents get distinct sessions.
- A directory whose basename is entirely punctuation resolves to `kmux_directory_<hash>`.
- Outside tmux: `kmux` attaches to a session whose pane is running `claude`.
- Inside tmux, from a different repo's session: `kmux` switches the client to the target
  session and does **not** nest a tmux inside a pane
  (`tmux display-message -p '#{session_name}'` confirms which one you landed in).
- `tmux kill-server`, restart tmux, and confirm Continuum restores the sessions
  (`~/.local/share/tmux/resurrect/` should have a `last` symlink after ~5 minutes,
  or force one with prefix + Ctrl-s).

## Constraints

- Don't reformat or "improve" the two config files above — they are the spec. If you
  believe something in them is wrong for this environment, say so and stop rather than
  silently diverging.
- Don't touch Claude Code's own config (`~/.claude*`), credentials, or any keychain.
- Keep the shell-rc edits to the minimum needed for PATH; no aliases, no prompt changes.

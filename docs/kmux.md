# kmux — build spec

`kmux` is a zero-argument command that puts you in **one persistent tmux session per
repository**. In the canonical variant that session runs Claude Code (`exec claude`).
Run it from anywhere inside a repo and you always land in that repo's session: it is
created the first time and reattached after that. Inside tmux it switches to the
session instead of nesting one tmux inside another.

Why: a Claude Code conversation (and its scrollback) keeps running when the terminal
or SSH link drops, when the devcontainer terminal tab closes, or when you jump between
repos. The session name is derived from the repo's path, so you never have to name or
look up a session yourself.

Sources (relative to repo root):

| File | What it is |
|---|---|
| `reference/kmux/variant-a/kmux` | Canonical script, runs `exec claude` in the session |
| `reference/kmux/variant-a/tmux.conf` | Canonical tmux config (has the `client-attached` hook) |
| `reference/kmux/variant-a/kmux-rebuild-prompt.md` | Earlier rebuild prompt: contract, prerequisites, procedure, acceptance checks |
| `reference/kmux/variant-b/kmux` | Variant: plain shell session, no `claude` |
| `reference/kmux/variant-b/tmux.conf` | Same config **without** the `client-attached` hook |

---

## 1. Behavior contract

These are numbered so tests can refer to them. Every item can be checked (see §6).

1. **No arguments.** If any argument is given, print `Usage: kmux` to stderr and exit **64**
   (`EX_USAGE`). Nothing else happens: no tmux call is made.
2. **Target directory.** Use `git rev-parse --show-toplevel`. Outside a repo, fall back
   to `pwd -P`. Then canonicalize the path with `cd -- "$repo" && pwd -P`, which resolves
   symlinks. A subdirectory of a repo therefore maps to the repo root.
3. **Session name** = `kmux_<safe>_<hash>`:
   - `<safe>`: the basename of the target directory. Every run of characters outside
     `[:alnum:]_-` is squeezed into a single `_` (`LC_ALL=C tr -cs '[:alnum:]_-' '_'`).
     Then one leading `_` and one trailing `_` are stripped. If the result is empty, use `directory`.
   - `<hash>`: the first 10 hex chars of `printf '%s' "$repo" | git hash-object --stdin`
     (no trailing newline is hashed).
   - Because the name depends on the full canonical path, two repos with the same basename
     under different parents get different sessions. The same path always gives the same session.
4. **Outside tmux** (`$TMUX` empty or unset): `exec tmux new-session -A -s "$session" -c "$repo" [cmd]`.
   `-A` attaches if the session exists and creates it otherwise.
5. **Inside tmux** (`$TMUX` set): never nest. If `tmux has-session -t "=$session"` fails,
   create the session detached (`new-session -d … -c "$repo" [cmd]`). Then
   `exec tmux switch-client -t "=$session"`.
6. **Exact matching.** Every `-t` target uses the `=` prefix, so tmux never picks another
   session whose name merely starts with this one.
7. **Hygiene.** The script runs with `set -euo pipefail`, and the final tmux call is `exec`'d
   so no wrapper bash process is left behind.
8. **Working directory.** The new session's starting directory is the canonical repo root (`-c "$repo"`).
9. **Idempotent.** Running kmux again for the same repo never creates a second session.

## 2. Canonical script

Install this exactly as written at `~/bin/kmux`. It is identical to
`reference/kmux/variant-a/kmux`.

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

## 3. Variants and how to choose

The two harvested scripts differ **only** in the session command. Both `new-session`
lines have it:

| Variant | Session command | What it gives you | Pick it when |
|---|---|---|---|
| claude-launching (variant A) | `'exec claude'` | The pane *is* Claude. If `claude` exits, the pane, window and (single-window) session end, so the next `kmux` starts a fresh Claude (inferred from tmux's default `remain-on-exit off`) | You want one keystroke to reach "Claude in this repo". This is the default |
| plain shell (variant B) | none, so tmux uses its default shell | A persistent shell rooted at the repo. Claude, if you use it, is started by hand and the session survives Claude exiting | You start a wrapper (e.g. `xclaude`/`xcodex`, see the sibling docs) or different tools per repo |

**Optional extension (a proposal, not in the sources).** If one script has to serve both
cases, keep the zero-argument contract (rule 1 still holds, so arguments still exit 64)
and read the command from the environment instead, for example
`cmd=${KMUX_CMD-exec claude}`. Pass `"$cmd"` only when it is non-empty, so
`KMUX_CMD= kmux` gives a plain shell. Note that the command only applies when the
session is **created**: `new-session -A` on an existing session and `switch-client`
both ignore it. Don't add positional arguments, because the usage/exit-64 behavior is
part of the contract.

## 4. tmux.conf essentials

Install as `~/.tmux.conf`. Use `reference/kmux/variant-a/tmux.conf` as is. It is
the newer config: the variant B one is the same file without one block.

**Diff between the two configs:** variant A adds just this:

```tmux
# A fresh attach detaches every other client. Orphaned clients from dropped
# terminals otherwise pile up (49 were attached on 2026-09-26) and the
# single-threaded server redraws every pane once per client -> input lag.
set-hook -g client-attached 'detach-client -a'
```

`kmux-rebuild-prompt.md` also embeds a tmux.conf, and it is the **pre-hook** version
(it matches the variant B file). Treat the variant A `tmux.conf` file as the source of truth over
the copy in that prompt.

Settings that matter, and why:

| Setting | Purpose |
|---|---|
| `set-hook -g client-attached 'detach-client -a'` | One live client at a time. Dropped terminals and devcontainer reconnects leave orphan clients attached. The server redraws for each one, and 49 of them caused input lag. **Side effect (inferred from `detach-client -a`, which detaches every other client on the server):** attaching from a second terminal kicks the first one off, even if it was on a different kmux session. Inside tmux, `kmux` uses `switch-client`, which does not attach a new client, so the hook should not fire there (inferred) |
| `default-terminal 'tmux-256color'` + `terminal-features …:RGB` | Truecolor inside the session, which Claude Code's TUI uses |
| `terminal-features ',xterm*:clipboard'` + `set -s set-clipboard on` | OSC 52 clipboard passthrough, so copying in tmux reaches the outer terminal/host |
| `mouse on`, `history-limit 100000` | Scroll through long agent output with the mouse wheel. The large scrollback is needed for that output |
| `mode-keys vi`, `aggressive-resize on` | vi copy mode. Window size follows the client that is actually looking at it rather than the smallest attached client |
| `status-position top`, `status-left ' #S '` | Shows the session name, `kmux_<repo>_<hash>`, so you can see which repo you are in |
| `monitor-activity on`, `visual-activity off`, `window-status-format '#{?window_activity_flag,!, }…'` | A background window that has new output gets a `!` marker, with no bell or popup |
| `status-right '#{continuum_status} …'` | Shows the Continuum autosave state. Without it, autosave still runs but you can't see it |
| `M-1…M-0`, `M-Left/Right` | Switch windows without the prefix key. `\|`/`-` split in the pane's cwd, `hjkl`/`HJKL` move between and resize panes, `z` zooms, `Enter` enters copy mode, `r` reloads the config |
| tpm + `tmux-resurrect` + `tmux-continuum`, `@continuum-save-interval '5'`, `@continuum-restore 'on'`, `@resurrect-capture-pane-contents 'on'` | Sessions and pane contents survive `tmux kill-server` or a container restart. A save runs every 5 minutes and is restored automatically when the server starts |
| `run-shell '~/.tmux/plugins/tpm/tpm'` **last** | Continuum registers its status-right hook when tpm runs. Anything placed after this line can override that hook and silently break autosave |

Prerequisites (from the rebuild prompt): **tmux ≥ 3.2** (needed for `terminal-features`;
the config was written against 3.5a). Install plugins with
`git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm && ~/.tmux/plugins/tpm/bin/install_plugins`.

## 5. Install procedure

1. **Check prerequisites.**
   - `tmux -V` must be ≥ 3.2. If the distro's package is older, put a newer build at `~/.local/bin/tmux`.
   - `git` must be on PATH. It is needed even outside a repo, because the name hash uses `git hash-object`.
   - Claude variant only: `claude` must resolve from a non-interactive shell. Check with
     `env -i HOME="$HOME" PATH="$PATH" sh -c 'command -v claude'`.
2. **Back up before you modify anything.**
   - Create `~/.config-backups/kmux-$(date -u +%Y%m%dT%H%M%SZ)/`.
   - Copy into it every path you will touch that already exists. Candidates: `~/bin/kmux`,
     `~/.local/bin/kmux`, `~/.tmux.conf`, `~/.profile`, `~/.bashrc`, `~/.zshrc`.
   - Write a `MANIFEST.txt` that lists each backed-up file with its original absolute
     path. It must also list explicitly each path that was **absent**, so a rollback
     knows to delete it rather than restore it.
3. **Install the script.**
   - Write `~/bin/kmux` and run `chmod 755 ~/bin/kmux`.
   - Run `ln -sfn ~/bin/kmux ~/.local/bin/kmux`.
4. **Check PATH.** The stock Debian-style `~/.profile` already prepends `~/bin` and
   `~/.local/bin`, but only if they **exist at login**. If you just created them,
   re-login or `export PATH="$HOME/bin:$HOME/.local/bin:$PATH"` for the current shell.
   Only edit rc files if PATH is actually missing them, and make only that change.
5. **Install the config.** Write `~/.tmux.conf`, then install tpm and the plugins. If a
   tmux server is already running, run `tmux source-file ~/.tmux.conf`.
6. **Make it idempotent.** A second install run must produce the same result. That
   means: overwrite the files with identical content, use `ln -sfn`, skip the tpm clone
   if `~/.tmux/plugins/tpm` exists, and only add PATH lines if they are missing. Each
   run takes a new timestamped backup and never overwrites an older one.
7. Do not touch `~/.claude*`, credentials, or keychains.
8. Run §6 and report what changed, plus how to roll it back (from the MANIFEST).

## 6. Verification checklist

Run these checks and keep the output. Don't assume they pass. `name` computes the
expected session name for the current directory:

```bash
name() { r=$(git rev-parse --show-toplevel 2>/dev/null || pwd -P); r=$(cd -- "$r" && pwd -P)
  s=$(printf %s "$(basename -- "$r")" | LC_ALL=C tr -cs '[:alnum:]_-' '_'); s=${s#_}; s=${s%_}
  printf 'kmux_%s_%s\n' "${s:-directory}" "$(printf '%s' "$r" | git hash-object --stdin | cut -c1-10)"; }
```

| # | Check | Command / expectation |
|---|---|---|
| 1 | Installed | `ls -l ~/bin/kmux ~/.local/bin/kmux`: mode `-rwxr-xr-x`, and the symlink points to `~/bin/kmux`. `command -v kmux` resolves |
| 2 | Arg → 64 (rule 1) | `kmux x; echo $?`: stderr shows `Usage: kmux`, and the exit code is `64`. `tmux ls` is unchanged |
| 3 | Same repo twice gives the same session (rules 3, 9) | In repo A: `kmux`, detach (`prefix d`), `kmux` again. `tmux ls \| grep -c "$(name)"` → `1` |
| 4 | A subdirectory maps to the repo root | `cd A/some/subdir && name` equals `name` run at the root of A |
| 5 | Same basename, different parents, different sessions | `mkdir -p /tmp/k1/app /tmp/k2/app`. Run `kmux` in each, then `tmux ls`: two `kmux_app_<hash>` sessions with different hashes |
| 6 | Punctuation-only basename | `mkdir -p '/tmp/k3/...' && cd '/tmp/k3/...' && name` → `kmux_directory_<hash>` |
| 7 | Inside tmux: switch, don't nest (rule 5) | From A's session, `cd` to repo B and run `kmux`. `tmux display-message -p '#S'` = B's name. `tmux list-clients` shows one client. `echo $TMUX` inside the pane shows a single server socket, and no tmux process runs inside a pane (`tmux list-panes -a -F '#{pane_current_command}'` has no `tmux`) |
| 8 | Session command | Claude variant: `tmux list-panes -t "=$(name)" -F '#{pane_current_command}'` → `claude` (or its node process). Plain variant: your shell |
| 9 | cwd (rule 8) | `tmux display-message -t "=$(name)" -p '#{pane_current_path}'` = the canonical repo root |
| 10 | No leftover wrapper (rule 7) | `pgrep -af 'bash .*kmux'` shows nothing while you are attached |
| 11 | Single client (variant A hook) | Attach from a second terminal. The first terminal is detached, and `tmux list-clients` shows 1 |
| 12 | Persistence | After about 5 minutes (or `prefix C-s`), `~/.local/share/tmux/resurrect/last` exists. Then `tmux kill-server`, start tmux again, and `tmux ls` shows the sessions restored |
| 13 | Rollback works | Every path in `MANIFEST.txt` either exists in the backup dir or is listed as absent |

## 7. Pitfalls and lessons

- **Orphaned clients cause input lag.** The tmux server is single-threaded and redraws
  for every attached client. 49 stale clients made typing lag (2026-09-26). The fix is the
  `client-attached` → `detach-client -a` hook. Check for the problem with `tmux list-clients | wc -l`.
- **`claude` missing from a non-interactive PATH kills the session immediately.** The
  pane runs `exec claude` without loading your interactive rc files. If `claude` is only
  on PATH through `.bashrc` aliases or nvm init, the session dies as soon as it is
  created, and `kmux` seems to "do nothing".
- **Session names must not depend only on the basename.** Many repos are called `app`,
  `web` or `api`. The path hash is what prevents collisions, and the `=` prefix prevents
  `kmux_app_ab…` from matching some other session's prefix.
- **Never nest tmux.** Running `tmux new-session -A` inside tmux either refuses
  ("sessions should be nested with care") or nests a tmux in the pane. Use `switch-client` when `$TMUX` is set.
- **Changing the session command does not affect existing sessions.** `-A` reattaches to
  whatever is already running. Kill the session (`tmux kill-session -t "=$(name)"`) to
  pick up a new command.
- **Renaming or moving a repo changes the hash.** The old session is orphaned rather
  than reused (inferred from the name derivation). Clean up with `tmux ls` / `kill-session`.
- **`~/.profile` checks directories at login.** If `~/bin` or `~/.local/bin` are created
  after login, they are not on PATH until you re-login.
- **`run-shell` for tpm must be the last line** of `.tmux.conf`, or Continuum autosave can break without any visible error.
- **Prefer the variant A config over the conf embedded in the rebuild prompt.** That copy predates the hook.

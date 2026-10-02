# dch — build spec

`dch` is a **host-side** shell function: `dch [folder]` brings up the folder's devcontainer
(builds it on the first run, starts it if stopped, no-op if running) and opens an interactive
shell inside it. It is the one command for "get me into this repo's container", locally and over
SSH on a server, and the outer half of the workflow whose inner half is `kmux`:

```
host$ cd ~/www/<org>/<repo> && dch     # container up, zsh inside it
container$ kmux                        # this repo's persistent tmux session, Claude in it
```

| File | Role |
|---|---|
| `reference/dch/dch.sh` | The function. Sourced from `~/.bashrc` / `~/.zshrc` |

Harvested from a working host `~/.bashrc`; the only change is the `DCH_SHELL` override.

## 1. Behavior contract

1. `dch` with no argument uses `$PWD`; `dch <folder>` uses `<folder>`. It does not walk up to the
   repo root: run it from the folder that holds `.devcontainer/`.
2. No `<folder>/.devcontainer/` directory → `no .devcontainer in <folder>` on stderr, return 1,
   and docker is never called.
3. `devcontainer up --workspace-folder <folder>` with stdout discarded (it is a JSON result
   blob); the CLI's progress log stays on stderr, so a failing build is visible. A non-zero exit
   returns that status and opens no shell.
4. `devcontainer exec --workspace-folder <folder> ${DCH_SHELL:-zsh}`. The container image must
   have zsh (every `mcr.microsoft.com/devcontainers/*` image does), or set `DCH_SHELL=bash`.
5. It is a function, not a script, so it works with whatever `devcontainer`/`docker` the
   interactive shell resolves. Re-running it while the container runs opens a second shell in
   the same container; it never rebuilds. Rebuild explicitly with
   `devcontainer up --workspace-folder . --remove-existing-container`.

## 2. Install

Prerequisites (host): `docker` usable without sudo, Node ≥ 18 + `npm install -g @devcontainers/cli`
(`devcontainer --version`). Report what is missing; install only if the user asked.

1. Back up `~/.bashrc` and `~/.zshrc` (AGENTS.md rule 1) into `~/.config-backups/dch-<UTC>/`.
2. **Existing `dch`?** `grep -nE '^\s*dch\s*\(\)' ~/.bashrc ~/.zshrc`. If one is defined inline,
   leave it in place and skip step 4 for that file. Report it; two definitions would shadow each
   other by load order.
3. Copy `reference/dch/dch.sh` to `~/.config/dch/dch.sh`.
4. For each rc file that exists, append (guarded by `grep -qF 'dch/dch.sh'`):
   `[ -f "$HOME/.config/dch/dch.sh" ] && . "$HOME/.config/dch/dch.sh"`
5. Never install `dch` *inside* a devcontainer — it drives docker from the host.

Server use (SSH to a box, same workflow as locally): the same install on the server, plus a git
key for the dev clone. Copy `.env*` files over with `scp` and `chmod 600` them; never commit them.

## 3. Verification checklist

| # | Check | Expectation |
|---|---|---|
| 1 | Defined | new shell: `type dch` → `dch is a function` (bash) / `dch is a shell function` (zsh) |
| 2 | Idempotent install | run the install twice; `grep -c 'dch/dch.sh' ~/.bashrc` → `1` |
| 3 | Missing folder | `dch /tmp; echo $?` → stderr `no .devcontainer in /tmp`, `1` |
| 4 | Up + exec (fake CLI) | `stub=$(mktemp -d); printf '#!/bin/sh\necho "[$*]" >&2\n' > $stub/devcontainer; chmod +x $stub/devcontainer; mkdir -p /tmp/dchx/.devcontainer; PATH="$stub:$PATH" dch /tmp/dchx` → `[up --workspace-folder /tmp/dchx]` then `[exec --workspace-folder /tmp/dchx zsh]` |
| 5 | Up failure stops | same with a stub that exits 1 on `up` → no `exec` line, status 1 |
| 6 | Real (optional) | in a repo with `.devcontainer/`: `dch`, then `echo $REMOTE_CONTAINERS $HOSTNAME` inside differs from the host |

## 4. Pitfalls

- `>/dev/null` hides only stdout. Don't add `2>&1`: build errors would vanish.
- `devcontainer exec` does not run `postCreateCommand`; `up` does, once per container. A failing
  post-create makes `up` exit non-zero, so `dch` never reaches the shell — fix post-create, don't
  bypass `up`.
- Two folders with the same `.devcontainer` contents are still two containers (the CLI keys the
  container by workspace path).

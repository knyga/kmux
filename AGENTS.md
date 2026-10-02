# Building kmux, xclaude, xcodex, editors, dch, devcontainers and tasks: procedure for agents

You were pointed here to install some or all of these tools in your current environment. The
home tools (kmux, xclaude, xcodex, their status bars, vim, nvim) go in `$HOME`; `dch` goes on the **host**
that runs docker. The per-project pieces, a **devcontainer** and **tasks** (a file-based task queue
plus the skills that drain it, i.e. the AI SDLC loop), go into a **project repository** and are
committed there.
The specs in `docs/` are the contract. The files in `reference/` are working
implementations: copy them and adapt where needed, but don't redesign them.

## Rules

1. **Back up before you modify.** Before touching `~/.bashrc`, `~/.zshrc`, `~/.profile`,
   `~/.tmux.conf`, `~/bin`, `~/.config/x*`, or a project's shared files (`AGENTS.md`, `CLAUDE.md`,
   `.gitignore`, `.claude/settings.json`, `.codex/hooks.json`, `.devcontainer/`), copy what exists into
   `~/.config-backups/<tool>-<UTC timestamp>/`. Add a `MANIFEST.txt` that lists what you backed up
   and what was absent.
2. **Never read, print, copy or log credentials.** That covers `.credentials.json`, `auth.json`,
   tokens and keychain entries. Check whether someone is logged in from file existence or from the
   tool's own status command. Never read the contents. Seeding a new profile must never copy credentials.
3. **Make it idempotent.** A second install must change nothing: guard rc-file lines with `grep -q`
   and don't create duplicate symlinks.
4. **Logging in is the user's job.** A profile that isn't logged in yet gets reported to the user. Don't work around it.
5. **Trust the code over prose.** Where a reference README and its script disagree, the
   `docs/*.md` spec says which one wins.

## Procedure

0. **Ask what to install. Always, before anything else.** Show this menu and let the user pick
   any subset (a multi-select prompt if your harness has one, e.g. Claude Code's AskUserQuestion,
   which takes at most 4 options per question, so split it into the groups below; otherwise
   print the numbered list and wait for the answer). Don't preselect, don't assume "all", and
   install nothing that wasn't picked.

   | # | Component | Where | What it gives |
   |---|---|---|---|
   | 1 | `kmux` | `$HOME` | One persistent tmux session per repo, Claude Code in it ([docs/kmux.md](docs/kmux.md)) |
   | 2 | `xclaude` | `$HOME` | Several Claude Code accounts, `xclaude <n>` ([docs/xclaude.md](docs/xclaude.md)) |
   | 3 | Claude status bar | `$HOME` | `statusline.py`: account, model, context, rate limits. With xclaude it goes into every profile, without it into the default profile only |
   | 4 | `xcodex` | `$HOME` | Several Codex accounts, `xcodex <n>` ([docs/xcodex.md](docs/xcodex.md)) |
   | 5 | Codex status bar | `$HOME` | Codex's native footer (model, branch, context, limits). With xcodex it is injected per run, without it written to the default `~/.codex/config.toml` |
   | 6 | `vim` | system package | Vim from the distro package manager ([docs/editors.md](docs/editors.md)) |
   | 7 | `nvim` | `$HOME` | Current stable Neovim from the official release, in `~/.local` ([docs/editors.md](docs/editors.md)) |
   | 8 | `dch` | host `$HOME` | `dch [folder]`: bring up a folder's devcontainer and open zsh in it ([docs/dch.md](docs/dch.md)) |
   | 9 | devcontainer | project repo | A `.devcontainer/` with full internet access, Claude + Codex, login volumes, and the picked home tools reinstalled on rebuild ([docs/devcontainer.md](docs/devcontainer.md)) |
   | 10 | tasks | project repo | The AI SDLC loop: task queue, CLI, skills, guard hook ([docs/tasks.md](docs/tasks.md)) |

   Group the question as **sessions and accounts** (1, 2, 4, plus 8 when you are on the docker
   host), **status bars and editors** (3, 5, 6, 7) and **per project** (9, 10). If 9 or 10 is
   picked, also ask **which repositories**, listing the checkouts you can see. Never offer this kit
   repo as a target. Restate the selection and the targets in one line before you start. When you
   run *inside* a devcontainer, say that 8 belongs on the host and that 1–7 are lost on rebuild
   unless 9's `KIT_COMPONENTS` reinstalls them.
1. **Check prerequisites** for the picked components only: `bash`, `git`, `tmux` (≥ 3.2) for
   kmux, `python3` (≥ 3.11 for tasks), `claude` and/or `codex` on a non-interactive `PATH`,
   `curl` + `tar` for nvim, `sudo` (or root) for vim, `docker` + `devcontainer` CLI for dch and
   devcontainer. Report any that are missing. Install
   them only if the user asked you to.
2. **kmux** (1): follow [docs/kmux.md](docs/kmux.md) § Install. Install
   `reference/kmux/variant-a/kmux` at `~/bin/kmux` (mode 755) and symlink
   `~/.local/bin/kmux` to it. Use `reference/kmux/variant-a/tmux.conf` as the source of truth
   for `~/.tmux.conf`; it is newer than the copy embedded in `kmux-rebuild-prompt.md`.
3. **xclaude** (2) **and/or Claude status bar** (3): follow [docs/xclaude.md](docs/xclaude.md)
   § Install. The files go in `~/.config/xclaude/` and are sourced from `~/.zshrc` and `~/.bashrc`:
   `[ -f "$HOME/.config/xclaude/xclaude.sh" ] && . "$HOME/.config/xclaude/xclaude.sh"`.
   - 2 + 3: run `install.sh`; it wires `statusline.py` into every profile.
   - 2 only: `XCLAUDE_STATUSLINE=0 install.sh`.
   - 3 only: copy just `statusline.py` to `~/.config/xclaude/` and merge the `statusLine` key
     into `${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json` (same JSON as install.sh, keep other keys).
4. **xcodex** (4) **and/or Codex status bar** (5): follow [docs/xcodex.md](docs/xcodex.md)
   § Install. The files go in `~/.config/xcodex/`, a hardcoded path, and are sourced the same way.
   - 4 + 5: as is; xcodex injects `tui.status_line` per run.
   - 4 only: also add `export XCODEX_STATUS_LINE=0` to the rc files (guarded).
   - 5 only: set `[tui] status_line = [...]` (the list in `xcodex.sh`'s `XCODEX_STATUS_ITEMS`) in
     the default `~/.codex/config.toml`, unless it already sets one. Never in the other profiles.
5. **vim** (6) **and/or nvim** (7): follow [docs/editors.md](docs/editors.md) § Install. Install
   the editor only; never create, overwrite or "improve" an existing `~/.vimrc`, `~/.vim/` or
   `~/.config/nvim/`.

   `reference/devcontainer/kit-bootstrap.sh` implements 1–7 unattended exactly this way; it is the
   executable reading of these steps.
6. **dch** (8): follow [docs/dch.md](docs/dch.md) § Install, on the host only.
7. **devcontainer** (9, per project): follow [docs/devcontainer.md](docs/devcontainer.md)
   § Install procedure in each named repo. Set `KIT_COMPONENTS` to the home tools picked in step 0,
   build it with `devcontainer up`, and commit `.devcontainer/` with an explicit pathspec.
8. **tasks** (10, per project): follow [docs/tasks.md](docs/tasks.md) § Install procedure. Install it in
   every project repository the user named. Never install it into this kit repo.
   `reference/tasks/install.sh <repo>` vendors `tools/tasks` + `tools/taskctl/`, creates `tasks/`
   and the skills, merges the guard hook, and appends a `## Task workflow` section to the project's
   `AGENTS.md`/`CLAUDE.md`. Then fill `tasks/gate.cmds` with the project's real lint/test commands and
   commit on `main` with the printed pathspec. A repo that already runs its own tracker is refused.
   Report it and leave it alone.
9. **Verify:** run every item in each picked component's "Verification checklist" and report pass
   or fail for each. Use the fake-binary tests where the real CLIs need a login. Run the tasks
   lifecycle checks in a throwaway clone, never in the user's checkout.
10. **Report:** what you installed and where (by menu item), the backup directory, which profiles
   are logged in (from `xclaude ls` / `xcodex ls`), which repos got a devcontainer and/or `tasks/`
   and what their `gate.cmds` runs, and what the user still has to do (e.g. `xclaude 2` then
   `/login`, `xcodex 2 login`, `exec zsh` to load the functions, logging in inside a new
   devcontainer, trusting the project's Codex hooks, or filing the first tasks with `/file-tasks`).

## In devcontainers

Claude/Codex config usually sits on a named volume (`~/.claude`, sometimes `~/.codex`).
Extra profile directories (`~/.claude-2`, `~/.codex-2`, …) and the files in `~/bin` and `~/.config` **are not on a volume, so
a rebuild loses them**. Tell the user. Suggest either adding volumes for them or
re-running the picked home tools from `postCreateCommand`; the devcontainer template (menu item 9)
does both: login volumes for profiles 1–2 and `kit-bootstrap.sh` with `KIT_COMPONENTS`. The tasks kit is the exception: it is committed in the
project, so a rebuild loses only the gitignored `.worktrees/` and leases, and the next `tools/tasks claim`
resumes or adopts the orphaned tasks.

## For automation (scripts, gates, runners)

`xclaude` and `xcodex` are **shell functions**, so programs can't spawn them. Spawn
`claude` / `codex` directly, with `CLAUDE_CONFIG_DIR` / `CODEX_HOME` set in the child's
environment. Fall back to another profile only when a run produced **no result** (usage limit, auth
failure, crash or timeout). Never re-run a completed judgment on another account to get a different answer.
See [docs/xcodex.md](docs/xcodex.md) § Integrating with automation. The task loop runs the same way:
`claude -p "/solve-next-task-loop"` or `codex exec '$solve-next-task-loop …'` with one persisted
`TASKS_SESSION` (`tools/tasks loop-state session`), so a retried run resumes its own task
([docs/tasks.md](docs/tasks.md) § Driving the loop).

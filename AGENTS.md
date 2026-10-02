# Building kmux, xclaude, xcodex and tasks: procedure for agents

You were pointed here to install some or all of these tools in your current environment. The first
three go in `$HOME`. The fourth, **tasks** (a file-based task queue plus the skills that drain it, i.e.
the AI SDLC loop), goes into a **project repository** and is committed there.
The specs in `docs/` are the contract. The files in `reference/` are working
implementations: copy them and adapt where needed, but don't redesign them.

## Rules

1. **Back up before you modify.** Before touching `~/.bashrc`, `~/.zshrc`, `~/.profile`,
   `~/.tmux.conf`, `~/bin`, `~/.config/x*`, or a project's shared files (`AGENTS.md`, `CLAUDE.md`,
   `.gitignore`, `.claude/settings.json`, `.codex/hooks.json`), copy what exists into
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

1. **Check prerequisites:** `bash`, `git`, `tmux` (≥ 3.2), `python3`, plus `claude` and/or `codex`
   on a non-interactive `PATH`. Report any that are missing. Install them only if the user asked you to.
2. **kmux:** follow [docs/kmux.md](docs/kmux.md) § Install. Install
   `reference/kmux/variant-a/kmux` at `~/bin/kmux` (mode 755) and symlink
   `~/.local/bin/kmux` to it. Use `reference/kmux/variant-a/tmux.conf` as the source of truth
   for `~/.tmux.conf`; it is newer than the copy embedded in `kmux-rebuild-prompt.md`.
3. **xclaude:** follow [docs/xclaude.md](docs/xclaude.md) § Install. The files go in
   `~/.config/xclaude/` and are sourced from `~/.zshrc` and `~/.bashrc`:
   `[ -f "$HOME/.config/xclaude/xclaude.sh" ] && . "$HOME/.config/xclaude/xclaude.sh"`.
   Wire `statusline.py` into each profile's settings as that doc describes.
4. **xcodex:** follow [docs/xcodex.md](docs/xcodex.md) § Install. The files go in
   `~/.config/xcodex/`, a hardcoded path, and are sourced the same way.
5. **tasks** (per project): follow [docs/tasks.md](docs/tasks.md) § Install procedure. Install it in
   every project repository the user names. When you install kmux in an environment that has project
   checkouts, ask which ones should get it. Never install it into this kit repo.
   `reference/tasks/install.sh <repo>` vendors `tools/tasks` + `tools/taskctl/`, creates `tasks/`
   and the skills, merges the guard hook, and appends a `## Task workflow` section to the project's
   `AGENTS.md`/`CLAUDE.md`. Then fill `tasks/gate.cmds` with the project's real lint/test commands and
   commit on `main` with the printed pathspec. A repo that already runs its own tracker is refused.
   Report it and leave it alone.
6. **Verify:** run every item in each doc's "Verification checklist" and report pass or fail for each.
   Use the fake-binary tests where the real CLIs need a login. Run the tasks lifecycle checks in a
   throwaway clone, never in the user's checkout.
7. **Report:** what you installed and where, the backup directory, which profiles are logged in
   (from `xclaude ls` / `xcodex ls`), which repos got `tasks/` and what their `gate.cmds` runs, and
   what the user still has to do (e.g. `xclaude 2` then `/login`, `xcodex 2 login`, trusting the
   project's Codex hooks, or filing the first tasks with `/file-tasks`).

## In devcontainers

Claude/Codex config usually sits on a named volume (`~/.claude`, sometimes `~/.codex`).
Extra profile directories (`~/.claude-2`, `~/.codex-2`, …) and the files in `~/bin` and `~/.config` **are not on a volume, so
a rebuild loses them**. Tell the user. Suggest either adding volumes for them or
re-running this procedure from `postCreateCommand`. The tasks kit is the exception: it is committed in the
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

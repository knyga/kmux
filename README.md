# kmux / xclaude / xcodex / dch / devcontainer / tasks — reference for agents

This repo is a **build reference**. Point a coding agent here and it can rebuild
the tools below in a new environment (a devcontainer or a host). The agent first asks which
ones you want (a menu, see `AGENTS.md` step 0) and installs only those:

| Tool | What it is | Spec |
|---|---|---|
| `kmux` | One command. It opens or switches to **one persistent tmux session per repository**, with Claude Code running in it. | [docs/kmux.md](docs/kmux.md) |
| `xclaude` | **Multiple Claude Code accounts (profiles).** `xclaude <n>` runs `claude` with `CLAUDE_CONFIG_DIR` set to profile *n*'s directory. It ships with a status line that shows the account, model, context and rate limits. | [docs/xclaude.md](docs/xclaude.md) |
| `xcodex` | The same idea for OpenAI Codex. `xcodex <n>` runs `codex` with `CODEX_HOME` set to profile *n*'s directory. | [docs/xcodex.md](docs/xcodex.md) |
| `dch` | Host-side. `dch [folder]` brings up the folder's devcontainer (builds it the first time) and opens zsh in it. | [docs/dch.md](docs/dch.md) |
| devcontainer | **Per project.** A `.devcontainer/` template with full internet access, Claude Code + Codex, logins on named volumes, no host credentials, and the picked home tools reinstalled on every rebuild. | [docs/devcontainer.md](docs/devcontainer.md) |
| `tasks` | **The AI SDLC loop, installed per project.** A file-based task queue (`tasks/<status>/NNNN-<slug>.md`, folder = status), the `tools/tasks` CLI that claims (lease + branch + worktree), gates and lands work, and the `solve-next-task` / `solve-next-task-loop` / `file-tasks` skills for Claude Code and Codex. | [docs/tasks.md](docs/tasks.md) |

The tools are independent of each other. kmux, xclaude and xcodex (and their status bars) live in
`$HOME`, `dch` on the docker host, and the devcontainer and `tasks` are committed into each project
repository. `dch` gets you into the container; `kmux` keeps the session; `xclaude`/`xcodex` pick
the account. When one account hits its usage limit, the next profile is a different account.

## Telling an agent to build them

Paste this into the target environment:

> Read `<path-to-this-repo>/AGENTS.md` and follow it: ask me which components to install, then
> install them here (and into `<project repo(s)>` for the per-project ones). Back up every file
> before you change it. Do not read or print any credential file.

## Layout

```
README.md          this file
AGENTS.md          step-by-step build procedure for an agent
docs/              one spec per tool: contract, install, verification, pitfalls
reference/         real implementations taken from working devcontainers (read-only)
  kmux/variant-a/      kmux (runs claude), tmux.conf, the original rebuild prompt
  kmux/variant-b/      kmux variant (plain shell), tmux.conf
  xclaude/variant-a/   README, install.sh, xclaude.sh, statusline.py
  xclaude/variant-b/   a statusline.py variant
  xcodex/              README, install.sh, xcodex.sh, xcodex.py
  dch/                 dch.sh (host-side function)
  devcontainer/        devcontainer.json, Dockerfile, post-create.sh (templates), kit-bootstrap.sh
  tasks/               install.sh, tools/ (tasks CLI + taskctl), template/ (tasks/, skills),
                       snippets/, tests/ (88 pytest cases)
```

## Where the references came from

Working copies harvested from the home directories of two devcontainers
(`~/bin/kmux`, `~/.tmux.conf`, `~/.config/xclaude/`, `~/.config/xcodex/`, sourced
from `~/.zshrc` / `~/.bashrc`). They lived only there — a container rebuild on a fresh
volume loses them — which is why this repo exists.

The `tasks` kit came from project repos rather than home directories: the `taskctl` CLI and solve
skills of a private project, themselves a distilled rewrite of a larger in-house tracker, generalized
here so they fit any repo. Provenance and the layers left out are in [docs/tasks.md](docs/tasks.md).

`dch` came from a host `~/.bashrc`, and the devcontainer template is distilled from several project
devcontainers that had converged on the same shape (full internet, login volumes, no host credentials).

# kmux / xclaude / xcodex — reference for agents

This repo is a **build reference**. Point a coding agent here and it can rebuild
the three terminal tools below in a new environment (a devcontainer or a host):

| Tool | What it is | Spec |
|---|---|---|
| `kmux` | One command. It opens or switches to **one persistent tmux session per repository**, with Claude Code running in it. | [docs/kmux.md](docs/kmux.md) |
| `xclaude` | **Multiple Claude Code accounts (profiles).** `xclaude <n>` runs `claude` with `CLAUDE_CONFIG_DIR` set to profile *n*'s directory. It ships with a status line that shows the account, model, context and rate limits. | [docs/xclaude.md](docs/xclaude.md) |
| `xcodex` | The same idea for OpenAI Codex. `xcodex <n>` runs `codex` with `CODEX_HOME` set to profile *n*'s directory. | [docs/xcodex.md](docs/xcodex.md) |

The tools are independent of each other. `kmux` keeps the session; `xclaude`/`xcodex` pick
the account. When one account hits its usage limit, the next profile is a different account.

## Telling an agent to build them

Paste this into the target environment:

> Read `<path-to-this-repo>/AGENTS.md` and follow it to install kmux, xclaude and xcodex
> here. Back up every file before you change it. Do not read or print any credential file.

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
```

## Where the references came from

Working copies harvested from the home directories of two devcontainers
(`~/bin/kmux`, `~/.tmux.conf`, `~/.config/xclaude/`, `~/.config/xcodex/`, sourced
from `~/.zshrc` / `~/.bashrc`). They lived only there — a container rebuild on a fresh
volume loses them — which is why this repo exists.

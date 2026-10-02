# devcontainer — build spec

How to give a project repository a `.devcontainer/` that an agent can live in: **unrestricted
internet access**, Claude Code and Codex preinstalled, logins that survive rebuilds, and the kit's
home tools (kmux, xclaude, xcodex, status bars) reinstalled on every rebuild. Enter it from the
host with [`dch`](dch.md), then run `kmux` inside.

| File | Goes to (in the target repo) | Role |
|---|---|---|
| `reference/devcontainer/devcontainer.json` | `.devcontainer/devcontainer.json` | Container definition, volumes, `KIT_COMPONENTS` |
| `reference/devcontainer/Dockerfile` | `.devcontainer/Dockerfile` | Base image + tmux/python3 + Claude Code + Codex CLI |
| `reference/devcontainer/post-create.sh` | `.devcontainer/post-create.sh` (mode 755) | Volume ownership, kit bootstrap, project deps, network check |
| `reference/devcontainer/kit-bootstrap.sh` | stays in the kit; post-create runs it from a kit clone | Unattended install of the home tools |

The template is distilled from several working project devcontainers that all converged on the same
shape. It is per project and committed there, like the tasks kit.

## 1. Design rules

1. **Full internet, on purpose.** No `init-firewall.sh`, no `--cap-add=NET_ADMIN/NET_RAW`, no
   egress allowlist, and the reason is written as a comment in `devcontainer.json`. Agents need
   the model APIs, package registries, GitHub and the project's own cloud services; an allowlist
   breaks silently the first time a dependency moves hosts. If the user asks for a *restricted*
   container instead, that is a different template: say so, don't half-apply this one.
2. **Credentials come in scoped, never wholesale.** Do not bind-mount host `~/.config/gcloud`,
   `~/.aws`, `~/.ssh`, `~/.kube` or similar. A mounted personal login gives every agent in the
   container everything the owner can reach, production included. Use a credential scoped to this project (a service-account
   key, a deploy key, a project API key) in the git-ignored `.secrets/` or `.env`, pointed to by
   env vars in `containerEnv`. Never bake a secret into the image.
3. **Logins live on named volumes.** One volume per profile directory: `~/.claude`, `~/.claude-2`,
   `~/.codex`, `~/.codex-2`, `~/.config/gh`. Volume names are `<project>-<what>-${devcontainerId}`,
   so two projects (or two clones) never share a login by accident.
4. **Tools are not on the volumes.** Claude Code and Codex are installed in the image. Codex is
   installed with `CODEX_HOME=~/.local/share/codex`, because installing into `~/.codex` would put
   the binaries under the volume, and the stale volume copy would hide every image upgrade.
5. **The `$HOME` layer is rebuilt; post-create rebuilds it.** `~/bin`, `~/.config/x*`,
   `~/.tmux.conf` and rc-file lines are lost on every rebuild. `post-create.sh` clones the kit and
   runs `kit-bootstrap.sh` with the components the user picked (`KIT_COMPONENTS`).
6. **`CLAUDE_CONFIG_DIR=/home/<user>/.claude` in `containerEnv`.** This makes a plain `claude` and
   `xclaude 1` the same profile (see [xclaude.md](xclaude.md) § 8).
7. **zsh is the shell.** `dch` opens zsh, and the VS Code terminal defaults to it. The
   `mcr.microsoft.com/devcontainers/*` images ship zsh plus a `vscode` (or `node`) user with
   passwordless sudo, which post-create needs for `chown`.

## 2. Install procedure

Target = a project repository the user named. Never this kit repo.

1. **Existing `.devcontainer/`?** If one exists, don't overwrite it. Show the user what differs
   from §1 (firewall present, host credential mounts, missing login volumes, …) and change it only
   with their go-ahead, after backing it up (AGENTS.md rule 1).
2. **Pick the base image from the project's stack**: read `package.json`, `pyproject.toml`,
   `go.mod`, `.nvmrc`, `.python-version` and CI config. Use the matching
   `mcr.microsoft.com/devcontainers/<stack>:<version>-bookworm` image, or `base:bookworm` with no
   stack. `node` images use the `node` user: then replace `vscode` with `node` everywhere
   (`remoteUser`, mount targets, paths in the Dockerfile and `CLAUDE_CONFIG_DIR`).
   Python ≥ 3.11 must be present if the tasks kit is (or will be) installed.
3. **Copy the three files** into `<repo>/.devcontainer/`, replace every `__PROJECT__` with the
   repository's directory name, `chmod 755 post-create.sh`. Check none is left:
   `grep -rn __PROJECT__ .devcontainer` → nothing.
4. **Set `KIT_COMPONENTS`** in `devcontainer.json` to the home tools the user chose in the
   AGENTS.md menu (any of `kmux xclaude claude-statusline xcodex codex-statusline`; empty string
   for none). If they did not choose xclaude/xcodex, drop the `-2` volumes and their `chown` lines.
5. **Project specifics**: dependency install in post-create's marked block, forwarded ports
   (`forwardPorts` + `portsAttributes`), stack extensions, service sidecars (switch to
   `dockerComposeFile` with an `app` service and keep the same volumes and env), and env vars for
   the scoped credentials (§1 rule 2).
6. **`.gitignore`**: make sure `.secrets/`, `.env`, `.env.*` (except an `.env.example`) are
   ignored. Back the file up first.
7. **Build it**: `devcontainer up --workspace-folder <repo>` (or `dch <repo>`). The run must end
   with the post-create banner; a failing post-create fails `up`.
8. **Commit** `.devcontainer/` (and `.gitignore`) in the project with an explicit pathspec. Don't push.
9. Tell the user what they must do: log in once inside the container (`claude` → `/login`,
   `codex login`, `gh auth login`, and `xclaude 2` / `xcodex 2 login` for spares). Logins persist
   on the volumes; nothing else does.

## 3. More profiles

The template mounts profiles 1–2. For profile 3 add, per tool,
`"source=<project>-claude-3-${devcontainerId},target=/home/vscode/.claude-3,type=volume"` and its
`chown` entry in post-create. Without a volume, `~/.claude-3` works but is lost on rebuild.

## 4. Verification checklist

Run inside the container (`dch <repo>`) after step 7.

| # | Check | Expectation |
|---|---|---|
| 1 | No firewall | `sudo iptables -S 2>/dev/null \| grep -c DROP` → `0` (or iptables absent); `grep -c -- --cap-add .devcontainer/devcontainer.json` → `0` |
| 2 | Internet | post-create's table shows an HTTP status (not `000`) for every host; `curl -sI https://example.com \| head -1` → `HTTP/… 200` |
| 3 | CLIs | `claude --version`, `codex --version`, `gh --version`, `tmux -V` (≥ 3.2), `python3 --version` all succeed |
| 4 | Codex outside the volume | `readlink -f "$(command -v codex)"` is not under `~/.codex` |
| 5 | Volumes owned by the user | `stat -c %U ~/.claude ~/.codex ~/.config/gh` → the remote user for each |
| 6 | Kit components | for each chosen component: `command -v kmux`; `type xclaude`; `type xcodex`; `jq .statusLine ~/.claude/settings.json` non-null (claude-statusline) |
| 7 | No host credentials | `ls ~/.config/gcloud ~/.aws ~/.ssh 2>&1` → absent, unless the user explicitly asked for one |
| 8 | Logins survive a rebuild | log in once, then `devcontainer up --workspace-folder . --remove-existing-container` from the host: `xclaude ls` still shows the login |
| 9 | Rebuild is idempotent | after the rebuild, `grep -c xclaude/xclaude.sh ~/.zshrc` → `1` |
| 10 | No placeholders, no secrets committed | `grep -rn __PROJECT__ .devcontainer` → nothing; `git ls-files .secrets .env` → nothing |

## 5. Pitfalls

- **Named volumes are root-owned** on first mount. Without the `sudo chown` loop, Claude fails to
  write its config and asks to log in again on every start.
- **The base image's stale Yarn apt source** (expired signing key) makes `apt-get update` fail in
  some `mcr` images. The Dockerfile removes it before `apt-get update`.
- **Host-built dependency dirs on the bind mount** (a macOS `.venv`, `node_modules` with native
  modules) break inside Linux. Put them on a named volume mounted over the workspace path.
- **`KIT_REPO` defaults to the public kit on GitHub.** Pin a fork or set `KIT_DIR` to a
  checkout already in the container (e.g. a mounted path) if the network policy or review process
  requires it.
- **`devcontainer exec` does not run post-create**; only `up` on a new container does. After editing
  post-create, rebuild with `--remove-existing-container`.

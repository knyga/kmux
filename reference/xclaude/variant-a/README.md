# xclaude — multiple Claude Code accounts on one machine

`xclaude` runs Claude Code against one of several **config directories**, chosen by a
1-based index, so several Claude accounts can coexist on one machine without ever
logging each other out. A shared status line then tells you, at a glance, *which*
account the session in front of you is using.

Everything lives in this one directory. To replicate it on another machine: copy
`~/.config/xclaude/` there and run `./install.sh`.

```
~/.config/xclaude/
├── xclaude.sh      shell functions: xclaude, xclaude ls, xclaude-seed
├── statusline.py   the status line renderer (both rows)
├── install.sh      idempotent installer for a fresh machine
└── README.md       this file
```

---

## 1. The mechanism it is built on

Claude Code reads **all** of its per-user state from one directory, and that directory
is selected by the `CLAUDE_CONFIG_DIR` environment variable (default `~/.claude`).
That single variable is the entire trick:

| Path inside the config dir | What it holds |
|---|---|
| `.credentials.json` | the OAuth access + refresh token (this is what "being logged in" *is*) |
| `.claude.json` | account identity (`oauthAccount.emailAddress`, `displayName`, …), per-project state, history |
| `settings.json` | model, theme, `statusLine`, hooks, permissions |
| `projects/`, `sessions/`, `history.jsonl` | transcripts and session state |
| `agents/`, `commands/`, `skills/` | your customisations |

So two directories = two fully independent installs sharing one binary. Nothing is
patched, and there is no plugin: `xclaude` is a ~30-line shell function that sets one
env var before `exec`-ing the real `claude`.

## 2. `xclaude.sh`

Sourced from `~/.zshrc` (and `~/.bashrc`). It is written to be correct in **both**
zsh and bash, which matters because zsh arrays are 1-based and bash arrays are
0-based — the `${XCLAUDE_DIRS[@]:$1-1:1}` slice syntax is 0-based in *both* shells,
so the 1-based user-facing index converts identically either way.

```sh
XCLAUDE_DIRS=("$HOME/.claude" "$HOME/.claude-2")   # <-- add a third entry to add an account
```

Commands it defines:

- **`xclaude <index> [claude args…]`** — `mkdir -p` the dir, then
  `CLAUDE_CONFIG_DIR="$dir" command claude "$@"`. `command` bypasses the function so it
  cannot recurse. All arguments pass straight through, so `xclaude 2 --resume`,
  `xclaude 2 -p "…"` and friends work unchanged.
- **`xclaude ls`** — prints each index, its path, and whether it `exists` and is
  `logged in` (a `.credentials.json` on Linux/WSL, or a Keychain entry on macOS).
- **`xclaude-seed <index>`** — copies *shared* config from `~/.claude` into another dir:
  `CLAUDE.md`, `settings.json`, `agents/`, `commands/`, `skills/`. It **deliberately
  never copies `.credentials.json` or `.claude.json`** — that would either clone your
  session token into a second identity or corrupt the account record. Each existing
  destination file is confirmed one at a time before being overwritten.

A bad index prints usage and returns 1 rather than silently defaulting to account 1 —
important, because silently landing in the wrong account is the failure mode this whole
tool exists to prevent.

### First-time login for a new account

```sh
xclaude 2        # empty config dir -> Claude Code runs its normal OAuth login
xclaude-seed 2   # optional: copy your skills/agents/settings across
```

## 3. `statusline.py` — the status line

Claude Code's `statusLine` setting runs an arbitrary command on every render, pipes a
JSON payload to it on **stdin**, and prints whatever the command writes to **stdout**
(multi-line output is supported; ANSI colors work; stderr is ignored). It renders:

```
👤 Alex │ ◆ Opus 5 (1M context) │ ⎇ main │ ▮ ctx 6%
⏱ session 6% (3h37m) │ week 53% (22h47m) │ Fable 100% (22h47m)
```

**Row 1 — who/what/where.**

| Field | Source |
|---|---|
| account | `$CLAUDE_CONFIG_DIR/.claude.json` → `oauthAccount.displayName` → `fullName` → `emailAddress` |
| model | payload `.model.display_name` |
| branch | `git -C <cwd> rev-parse --abbrev-ref HEAD` (detached HEAD → short SHA, no repo → `-`) |
| context % | payload `.context_window.used_percentage` |

The account name is the reason this exists. The payload does **not** carry the user's
identity, so the script re-derives it from the config dir it was launched with —
`CLAUDE_CONFIG_DIR` is inherited by the hook subprocess, and falls back to `~/.claude`
when unset (i.e. a plain `claude` invocation).

**Row 2 — rate limits.** These come from two sources, merged:

1. **The payload's `rate_limits`** (`five_hour`, `seven_day`; `spend_limit` on gateway
   auth). Live and free, but it has **no per-model breakdown** and is absent until the
   session's first API response lands.
2. **`GET https://api.anthropic.com/api/oauth/usage`**, cached. Its `limits[]` array is
   the general form — `kind: "session" | "weekly_all" | "weekly_scoped"`, each with
   `percent` and `resets_at`, the scoped ones naming their model in
   `scope.model.display_name`. This is the only place the **Fable / Opus / Sonnet**
   weekly gauges exist. Headers: `Authorization: Bearer <accessToken>` and
   `anthropic-beta: oauth-2025-04-20`.

The payload wins for session/week (freshest); the cache fills in the scoped model
gauges, and also covers session/week before the first API response.

**The cache never blocks a render.** `$CLAUDE_CONFIG_DIR/statusline-usage.json`, 120 s
TTL. When it is stale the render spawns a *detached* `statusline.py --refresh` child and
draws with whatever it already has, so the status line is always instant (measured
~21 ms warm). A `.lock` file with `O_EXCL` prevents a refresh stampede and is stolen
after 60 s if a refresher dies. Percentages are colored green / yellow ≥60 / red ≥80,
and resets render as compact deltas (`3d1h`, `4h13m`, `45m`, `<1m`).

**Credentials are read, never written.** If the access token has expired the fetch is
simply skipped — Claude Code refreshes `.credentials.json` on its own schedule, and
rotating the refresh token ourselves could invalidate the CLI's stored credentials.
Every failure path (no token, no network, HTTP error, malformed JSON) degrades to the
payload-only row rather than breaking the status line.

**macOS caveat.** Linux and WSL store credentials as plaintext JSON in the config dir.
macOS uses the login Keychain instead, and the Keychain *service* name is not stable
across config dirs. `statusline.py` tries
`security find-generic-password -a claude-code-user -w -s "Claude Code-credentials"`;
if that guess is wrong for your setup, find the real name with

```sh
security dump-keychain | grep -i 'svce.*[Cc]redentials'
```

and export `XCLAUDE_KEYCHAIN_SERVICE=<name>`. If it cannot read a token at all, row 2
still shows session/week from the payload — only the per-model gauges go missing.

## 4. `install.sh`

Idempotent. Run it after copying the directory to a new machine:

1. Verifies `python3` (the only hard dependency) and that both scripts are present;
   `chmod +x` them.
2. Reads `XCLAUDE_DIRS` by sourcing `xclaude.sh` **in a subshell** — the list is defined
   in exactly one place and the installer never leaks the functions into your shell.
3. Appends the `source` line to `~/.zshrc` and `~/.bashrc` if not already present.
4. For each config dir: `mkdir -p`, then merges `statusLine` into `settings.json`
   (creating the file if absent) via an atomic `os.replace`, **preserving every other
   key** — `model`, `theme`, hooks, permissions are untouched.

The `statusLine.command` is written as an **absolute** path resolved at install time, so
it is correct whatever `$HOME` is on the new machine. (`~` is also accepted by Claude
Code if you prefer to hand-edit it.)

## 5. Adding a third account

```sh
$EDITOR ~/.config/xclaude/xclaude.sh     # XCLAUDE_DIRS=(… "$HOME/.claude-3")
~/.config/xclaude/install.sh             # installs the status line into the new dir
exec $SHELL
xclaude 3                                # logs in
xclaude-seed 3                           # optional: copy skills/agents/settings
```

## 6. Notes and limits

- **Not a sandbox.** Separate accounts, one filesystem and one user. Sessions can see
  each other's files; this isolates *identity and Claude state*, nothing else.
- **Per-account caches** (`statusline-usage.json`) live inside each config dir, so they
  never mix and are removed with the account.
- **API traffic:** one `GET /api/oauth/usage` per account at most every 120 s, and only
  while a session is actually rendering a status line.
- **Version dependency:** the two-row status line reads `context_window.used_percentage`
  and `rate_limits`, which require a reasonably recent Claude Code (verified on 2.1.260).
  On an older build those fields are simply absent and the affected parts degrade
  gracefully — context shows `0%`, row 2 falls back to the cached API numbers.

# xclaude: build spec

`xclaude` runs Claude Code against one of several **config dirs** (profiles), picked by a
1-based index, so several Claude accounts can live on one machine or devcontainer without
logging each other out. A shared status line shows **which account** the current session is
on and how much of its usage limits is left.

Why you want it:
- Several Claude accounts (personal, work, a spare). When one hits its 5-hour or weekly
  limit, keep working in `xclaude 2` without logging out of account 1.
- Starting a session on the wrong account by accident is the failure this tool exists to
  prevent. That is why a bad index is an error and never falls back to account 1, and why
  the status line names the account.

Reference implementation (read these, don't guess):

| File | Role |
|---|---|
| `reference/xclaude/variant-a/xclaude.sh` | shell functions (the CLI). Canonical. |
| `reference/xclaude/variant-a/statusline.py` | status line, variant A (two rows, with clocks and pace) |
| `reference/xclaude/variant-a/install.sh` | idempotent installer |
| `reference/xclaude/variant-a/README.md` | the original author's design notes (partly out of date, see §9) |
| `reference/xclaude/variant-b/statusline.py` | status line, variant B (sturdier, see §5) |
| `reference/xcodex/` | sister tool for Codex (`CODEX_HOME`). Uses the same conventions. |

Install layout (the whole directory is what you copy to a new machine):

```
~/.config/xclaude/
├── xclaude.sh      sourced by ~/.zshrc and ~/.bashrc; defines xclaude, xclaude-seed
├── statusline.py   status-line command, shared by every profile
├── install.sh      idempotent installer
└── README.md
```

---

## 1. Mechanism

Claude Code keeps all of its per-user state in one directory, chosen by the env var
`CLAUDE_CONFIG_DIR` (the default is `~/.claude`). Two dirs give you two independent
installs that share one `claude` binary. Nothing is patched. `xclaude` only sets that one
variable for the child process.

| Inside `$CLAUDE_CONFIG_DIR` | Contents |
|---|---|
| `.credentials.json` | OAuth access and refresh token (Linux/WSL). This file *is* the login. **Secret.** |
| `.claude.json` | account identity (`oauthAccount.emailAddress/displayName/fullName`), onboarding flags, per-project trust, history |
| `settings.json` | model, theme, `statusLine`, hooks, permissions |
| `projects/`, `sessions/`, `history.jsonl` | transcripts |
| `agents/`, `commands/`, `skills/`, `CLAUDE.md` | customisations you can share between profiles |
| `statusline-usage.json[.lock]` | written by xclaude: per-profile usage cache |

Where the global config lives when `CLAUDE_CONFIG_DIR` is **unset**: `~/.claude.json` in
`$HOME`, not `~/.claude/.claude.json`. Variant B relies on this (its `account_name()`
checks `~/.claude.json` first when the variable is unset). This matters in §8.

On macOS the credentials are stored in the login Keychain, not in `.credentials.json` (see §5.4).

## 2. Profiles → dirs

All profiles are defined in a single array in `xclaude.sh`. Nothing else holds the list:
`install.sh` reads it by sourcing the file in a subshell.

```sh
XCLAUDE_DIRS=("$HOME/.claude" "$HOME/.claude-2" "$HOME/.claude-3" "$HOME/.claude-4")
```

Index `N` maps to `XCLAUDE_DIRS[N-1]`, so `1` is `~/.claude` (the default profile) and `N`
is `~/.claude-N`. To add a profile, add an entry and re-run `install.sh`. xcodex follows the
same pattern: `XCODEX_DIRS=(~/.codex ~/.codex-2 …)`.

## 3. CLI contract

`xclaude.sh` must work when sourced by **both bash and zsh**. Use only POSIX-ish constructs
plus arrays. To read the array by index, use the slice `${XCLAUDE_DIRS[@]:$1-1:1}`. It is
0-based in both shells, which sidesteps the fact that zsh indexes `arr[i]` from 1 and bash
from 0. Don't use `${arr[$i]}`.

| Command | Behavior |
|---|---|
| `xclaude ls` | For each dir prints `  N) <path> [exists\|missing[, logged in]]`. "Logged in" means `.credentials.json` exists, or on Darwin a `security find-generic-password -s "Claude Code-credentials"` lookup succeeds. Returns 0. The file is only tested for existence and never read. |
| `xclaude <N> [args…]` | Checks that N is all digits and within 1..len, otherwise prints usage plus the list **to stderr** and returns 1. Then: `mkdir -p` the dir, run `_xclaude_bootstrap` (below), print `xclaude: prepared <dir> (log in when prompted)` to stderr if `.claude.json` was missing, then `CLAUDE_CONFIG_DIR="$dir" command claude "$@"`. |
| `xclaude-seed <N>` | Copies shared config from `~/.claude` into profile N: `CLAUDE.md settings.json agents commands skills`. Asks `overwrite <path>? [y/N]` before replacing each item that already exists (then `rm -rf` followed by `cp -R`, so it replaces rather than merges). Refuses when N resolves to `~/.claude`. **Never copies `.credentials.json` or `.claude.json`.** |
| `xclaude` (no args) or a bad index | usage on stderr, return 1. |

Argument passthrough: every argument after the index goes to `claude` unchanged
(`xclaude 2 --resume`, `xclaude 2 -p "…"`, `xclaude 3 --dangerously-skip-permissions`).
`command claude` skips shell functions, so a wrapper named `claude` can't cause recursion.
The real implementation runs `claude` as a child process (no `exec`), so the shell function
returns claude's exit code. The README says "exec-ing", which is wrong.

### `_xclaude_bootstrap <dir>` (first-run wizard skip)

Runs from both `xclaude` and `xclaude-seed`. If `<dir>/.claude.json` is missing, it writes
only **non-credential** state:

```json
{ "hasCompletedOnboarding": true, "bypassPermissionsModeAccepted": true,
  "installMethod": "native", "autoUpdates": false,
  "projects": { "<path>": { "hasTrustDialogAccepted": true, "allowedTools": [], "mcpServers": {} } } }
```

The trusted paths come from `XCLAUDE_TRUST_DIRS`, one per line (default `$PWD`). awk
escapes them as JSON strings, so paths with spaces or quotes work. If the dir has no
`settings.json` yet, it copies `~/.claude/settings.json`, which brings the theme and
`statusLine` along. It never modifies an existing `.claude.json`. You still log in yourself.

### Env vars

| Var | Read by | Meaning |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | Claude Code, statusline | profile dir. xclaude sets it for the child process. The status line inherits it. |
| `XCLAUDE_TRUST_DIRS` | bootstrap | newline-separated paths to pre-trust (default `$PWD`) |
| `XCLAUDE_KEYCHAIN_SERVICE` | statusline (macOS) | override for the Keychain service name |
| `XCLAUDE_PROFILE` | statusline variant B only | if set and different from the account name, row 1 shows `<account> (<profile> profile)`. *Nothing in the reference sets it. Presumably the devcontainer env did.* |

## 4. Install (`install.sh`)

The installer is idempotent, so re-running it after an upgrade or a fresh clone is safe. Steps:

1. `set -euo pipefail`. Requires `python3` (the only hard dependency besides `claude` and
   `git`). Checks that `xclaude.sh` and `statusline.py` exist, then `chmod +x`.
2. `dirs=$( . "$here/xclaude.sh"; printf '%s\n' "${XCLAUDE_DIRS[@]}" )`. The subshell keeps
   the functions out of the installer's shell.
3. For `~/.zshrc` and `~/.bashrc`, **if the file exists** and `grep -qF 'xclaude/xclaude.sh'`
   finds nothing, it appends:
   `[ -f "$HOME/.config/xclaude/xclaude.sh" ] && . "$HOME/.config/xclaude/xclaude.sh"`
   It never creates a missing rc file.
4. For each dir: `mkdir -p`, then a Python snippet merges this into `settings.json`
   ```json
   "statusLine": { "type": "command", "command": "<ABSOLUTE path to statusline.py>", "padding": 0 }
   ```
   It keeps every other key and writes `.tmp` followed by `os.replace` (atomic). A missing
   file starts from `{}`. A non-object or invalid JSON file makes the install **fail**
   rather than get clobbered.

The status-line path is resolved to an absolute path at install time, so it is correct for
whatever `$HOME` the machine has. Because step 4 runs `mkdir -p`, every profile dir exists
after install. "exists" in `xclaude ls` therefore tells you nothing, and only "logged in"
matters.

Devcontainer recipe (inference, assembled from the context given, not from a harvested
devcontainer.json): bake or copy `~/.config/xclaude/` into the image or dotfiles. Run
`install.sh` in `postCreateCommand`, because the rc files must exist by then. The container
sets `CLAUDE_CONFIG_DIR=$HOME/.claude` and mounts a named volume on `~/.claude`. See §8 for
the extra profiles.

## 5. Status line (`statusline.py`)

Claude Code's `statusLine` runs the command on every render. It sends a JSON payload on
stdin and shows the command's stdout (several lines and ANSI colors are fine, stderr is
ignored). Example output:

```
👤 you@example.com │ ◆ Opus 5 (1M context) │ ⎇ main │ ▮ ctx 6%
⏱ session 6% (3h37m) │ week 53% (22h47m) │ Fable 100% (22h47m)
```

### 5.1 Row 1: who / what / where

| Field | Source |
|---|---|
| account | `$CLAUDE_CONFIG_DIR/.claude.json` → `oauthAccount`: first non-empty of `emailAddress`, `displayName`, `fullName` (the order in both variants' code). `?` if none. The payload does **not** include identity, which is why the script exists. |
| model | payload `.model.display_name` (variant A falls back to `.model.id`) |
| branch | `git -C <payload.workspace.current_dir \| payload.cwd>`. Short SHA when HEAD is detached, `-` outside a repo. |
| ctx | payload `.context_window.used_percentage` |
| clocks (A only) | local `HH:MM TZ`, plus `America/Los_Angeles` time when it is a different zone |

### 5.2 Row 2: rate limits, from two merged sources

1. **Payload `rate_limits`**: `five_hour` → "session", `seven_day` → "week", each with
   `used_percentage` and `resets_at` (unix seconds). Live and free, but it has no
   per-model breakdown and is missing until the session's first API response.
2. **`GET https://api.anthropic.com/api/oauth/usage`**, cached. Headers:
   `Authorization: Bearer <claudeAiOauth.accessToken>` and `anthropic-beta: oauth-2025-04-20`.
   The body is `limits[]` with `kind` set to `session | weekly_all | weekly_scoped`, plus
   `percent` and `resets_at` (ISO-8601). Scoped entries name their model in
   `scope.model.display_name`. This is the only source for the per-model weekly gauges
   (Fable, Opus, Sonnet…).

For session and week the payload wins because it is fresher. The cache fills in the scoped
gauges, and also covers session and week before the first response arrives. Percentages are
green below 60, yellow from 60, red from 80. Reset times are compact deltas (`3d1h`,
`4h13m`, `45m`, `<1m`).

### 5.3 Cache, lock, TTL, never-block

- Cache file `$CLAUDE_CONFIG_DIR/statusline-usage.json`, one per profile so they never mix,
  with `CACHE_TTL = 120` s.
- When a render finds the cache stale or missing, it spawns a **detached**
  `statusline.py --refresh` (`start_new_session=True`, stdio set to DEVNULL) and **draws
  immediately with whatever is cached**. A render never waits on the network. The author
  measured about 21 ms warm.
- The refresher takes `statusline-usage.json.lock` through `O_CREAT|O_EXCL` (mode 0600),
  steals it if older than `60` s (a dead refresher), fetches with an 8 s timeout, writes
  `<cache>.tmp.<pid>` and then calls `os.replace`, and removes the lock in `finally`.
- If the token is missing, or `expiresAt` (in ms) is in the past, it **skips the fetch**.
  It **never refreshes or rotates credentials**. Claude Code refreshes `.credentials.json`
  on its own schedule, and if xclaude used the refresh token it could invalidate the CLI's
  stored credentials. Credentials are read-only to xclaude.
- Any failure (no token, network down, HTTP error, bad JSON) falls back to a payload-only
  row 2. The status line must never break.
- API traffic: at most one GET per profile every 120 s, and only while a session is rendering.

### 5.4 macOS Keychain

On Linux/WSL the token is plaintext JSON in `.credentials.json`. On macOS it lives in the
Keychain:
- Variant A tries `security find-generic-password -a claude-code-user -w -s "Claude Code-credentials"`
  (or `$XCLAUDE_KEYCHAIN_SERVICE`).
- Variant B derives the service name per config dir. When `CLAUDE_CONFIG_DIR` is unset it
  uses `Claude Code-credentials`. Otherwise it uses
  `Claude Code-credentials-` + `sha256(NFC(CLAUDE_CONFIG_DIR))[:8]`. That is the
  `hashlib`/`unicodedata` import. It tries account `$USER` and then `claude-code-user`.
  *Inference: this mirrors how Claude Code names per-config-dir Keychain items. That is
  plausible but unverified here.*
- To find the real name: `security dump-keychain | grep -i 'svce.*[Cc]redentials'`.
- Without a token, row 2 still shows the payload's session and week, and only the scoped
  gauges are missing.

### 5.5 Variant A vs variant B

| Aspect | A | B |
|---|---|---|
| Keychain service | one fixed name (or env override) | per-dir `sha256` hash (see 5.4), tries `$USER` then `claude-code-user` |
| Account file when `CLAUDE_CONFIG_DIR` unset | `~/.claude/.claude.json` only (likely `?` on a default install) | `~/.claude.json` first, then `~/.claude/.claude.json`. Last fallback is the basename of the config dir. |
| Profile label | none | `XCLAUDE_PROFILE` suffix |
| Cache body key | `{"fetched_at", "usage"}` | `{"fetched_at", "data", "error"?}`. **Incompatible.** Both use the same filename. |
| Failed fetch | writes nothing, so every later render spawns a refresher (the lock limits it to one at a time) | writes `fetched_at` plus `error` and keeps the old `data`, so it backs off for 120 s |
| Usage API shapes | `limits[]` only | `limits[]`, plus a legacy top-level shape (`five_hour`, `seven_day`, `seven_day_opus`, `seven_day_sonnet` with `utilization`) |
| Timestamps | unix seconds or ISO | also epoch milliseconds (values > 1e11 count as ms) and numeric strings |
| Spend | `usage.spend.enabled` → "credits" gauge | payload `rate_limits.spend_limit` → "spend" gauge |
| Pace indicator | `tNN%` = share of the window's time already elapsed, colored by how far usage runs ahead of time (≥10 yellow, ≥25 red) | none |
| Clocks | local time plus LA | none |
| git | `rev-parse --abbrev-ref HEAD`, 2 s timeout | `symbolic-ref --short -q HEAD` (works on an unborn branch), `-c gc.auto=0`, 1 s timeout |
| Top-level guard | none (an exception produces an empty status line) | `try/except` prints `👤 xclaude statusline error: …` |
| Lock file | empty | holds the pid. Steal-and-retry loop. |

Recommendation for a new build: use **variant B's robustness** (per-dir Keychain hash,
`~/.claude.json` fallback, writing errors to the cache for backoff, the top-level guard,
the unborn-branch handling). Optionally add A's pace and clock features. Don't mix the two
cache formats.

## 6. Verification checklist

None of these commands print credential contents.

```sh
bash -n ~/.config/xclaude/xclaude.sh && zsh -n ~/.config/xclaude/xclaude.sh
python3 -m py_compile ~/.config/xclaude/statusline.py
~/.config/xclaude/install.sh && ~/.config/xclaude/install.sh          # 2nd run must be a no-op for rc files
grep -c 'xclaude/xclaude.sh' ~/.bashrc ~/.zshrc                        # each: 1
bash -ic 'type xclaude' ; zsh -ic 'type xclaude'                      # function in both shells
xclaude ls                                                            # every index listed, 1-based
xclaude 0; echo $?; xclaude 99; echo $?; xclaude abc; echo $?         # usage on stderr, 1 each
for d in ~/.claude ~/.claude-2; do python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["statusLine"])' "$d/settings.json"; done
# render as profile 2 with a fake payload, timed (must be fast and print 2 lines):
time (echo '{"model":{"display_name":"Test"},"workspace":{"current_dir":"'"$PWD"'"},"context_window":{"used_percentage":12},"rate_limits":{"five_hour":{"used_percentage":30,"resets_at":'$(( $(date +%s)+3600 ))'}}}' \
  | CLAUDE_CONFIG_DIR=~/.claude-2 ~/.config/xclaude/statusline.py)
echo '' | ~/.config/xclaude/statusline.py                             # empty stdin must not crash
sleep 3; python3 -c 'import json,sys;c=json.load(open(sys.argv[1]));print(sorted(c))' ~/.claude-2/statusline-usage.json  # keys only
test -f ~/.claude-2/.credentials.json && echo "creds present"         # existence only, never cat
xclaude 2 --version                                                   # arg passthrough reaches claude
```

Manual check: open `xclaude 1` and `xclaude 2` side by side. Row 1 must show two different
accounts, and logging out of one must not affect the other.

## 7. Security rules (non-negotiable)

- Never `cat`, print, log, copy, or commit `.credentials.json`, Keychain secrets, or
  tokens. Check for existence only (`test -f`, `security … >/dev/null`).
- `xclaude-seed` and any seeding you write must **exclude** `.credentials.json` and
  `.claude.json`. Copying them clones a session into a second identity or corrupts the
  account record.
- The status line may read the access token **only** to call `/api/oauth/usage`, and only
  in the refresher. It must never use the refresh token and never write credentials.
- The cache and lock are created 0600 or via `os.replace`. The cache holds usage
  percentages, not secrets.
- The bootstrap pre-accepts `bypassPermissionsModeAccepted` and trust for `$PWD` (or
  `XCLAUDE_TRUST_DIRS`). That is deliberate for devcontainers. On a host, keep the trusted
  set narrow.
- This is not a sandbox. Every profile runs as the same OS user on the same filesystem.
  Only identity and Claude state are isolated.

## 8. Pitfalls

- **`claude` vs `xclaude 1` on a host without `CLAUDE_CONFIG_DIR`.** A plain `claude` uses
  `~/.claude.json`, while `xclaude 1` sets `CLAUDE_CONFIG_DIR=~/.claude` and so uses
  `~/.claude/.claude.json`. *Inference:* these can be two different global states, so the
  bootstrap may also run for index 1. In devcontainers that export
  `CLAUDE_CONFIG_DIR=$HOME/.claude` the two are the same.
- **Only `~/.claude` is on the named volume.** `~/.claude-2…N` live in the container layer
  and **are lost on rebuild** unless you mount a volume per profile or put the profiles
  under a persisted path. *Inference from the stated setup.*
- An exported `CLAUDE_CONFIG_DIR` doesn't break xclaude, because the per-command assignment
  overrides it. It does mean a plain `claude` is whichever profile the env points at.
- macOS `xclaude ls` (variant A logic) checks one fixed Keychain service, so every profile
  can show as "logged in" whenever the default profile is. Use variant B's per-dir hash.
- A leading zero is octal in bash arithmetic, so `xclaude 08` fails in the slice. Only
  plain integers are supported.
- Variant A has no top-level guard, so a payload that isn't a JSON object, or an unexpected
  type, can blank the status line. Wrap `main()`.
- The two variants share one cache filename with different body keys. After switching,
  expect a stale-looking row 2 until the next refresh (≤120 s).
- `context_window.used_percentage` and `rate_limits` need a recent Claude Code (the author
  verified 2.1.260). On older builds ctx shows 0% and row 2 comes from cache only.
- `install.sh` skips missing rc files. If the container has no `~/.zshrc` at install time,
  re-run the installer after the rc file exists.
- `xclaude-seed` replaces existing directories (`rm -rf` then `cp -R`). It doesn't merge
  them the way `xcodex-seed` does.

## 9. Places where the reference README disagrees with the code (trust the code)

- The README shows 2 dirs, but the code ships 4 (`~/.claude` … `~/.claude-4`).
- The README says account precedence is `displayName → fullName → emailAddress`. Both
  scripts actually try `emailAddress` first.
- The README doesn't document `_xclaude_bootstrap` or `XCLAUDE_TRUST_DIRS`, nor variant A's
  clocks and pace indicator.
- The README says xclaude "exec-s" claude. It actually runs `command claude` in the
  function's process, without `exec`.

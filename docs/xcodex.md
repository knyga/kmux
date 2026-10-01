# xcodex — build spec

Audience: a coding agent rebuilding `xcodex` in a fresh environment. The real,
working implementation (taken from a working devcontainer) is in
`../reference/xcodex/`:

| File | Role |
|---|---|
| `reference/xcodex/xcodex.sh` | Bash/Zsh functions: `xcodex`, `xcodex ls`, `xcodex-seed`; holds `XCODEX_DIRS` |
| `reference/xcodex/xcodex.py` | Credential-safe helper: `identity <dir>` (account label), `seed <src> <dst>` |
| `reference/xcodex/install.sh` | Idempotent installer |
| `reference/xcodex/README.md` | User-facing README |

The fastest correct build is to copy these four files to `~/.config/xcodex/` and
run `install.sh`. The rest of this document is the contract you must keep if you
change anything. Statements marked **(inference)** are not stated in the source;
everything else comes from the code or from recorded real-world use.

Sibling tool with the same conventions (1-based index, `ls`, `-seed`, installer
sourced from rc files): `reference/xclaude/variant-a/` (`CLAUDE_CONFIG_DIR`
instead of `CODEX_HOME`).

---

## 1. What and why

Codex CLI keeps all per-user state (login in `auth.json`, sessions, history,
`config.toml`, skills, plugins, caches, memories, local DBs) under one directory
chosen by `CODEX_HOME` (default `~/.codex`). `xcodex` runs the installed `codex`
with `CODEX_HOME` pointed at one of several directories, selected by a 1-based
index. Each directory is an independent account, so logging one in or out never
disturbs another, and a usage limit on one account is not a limit on the box.

**A profile is a `CODEX_HOME` directory and nothing else.** There is no other
state, registry, or config. This is the single most important fact for
automation (section 5).

What it isolates: account identity and Codex state. What it does not: the
filesystem or OS user — all profiles run as the same user.

---

## 2. Profile directory mapping

From `xcodex.sh` line 3:

```sh
XCODEX_DIRS=("$HOME/.codex" "$HOME/.codex-2" "$HOME/.codex-3" "$HOME/.codex-4")
```

| Index | `CODEX_HOME` |
|---|---|
| 1 | `~/.codex` (Codex's default home — profile 1 is "plain `codex`") |
| 2 | `~/.codex-2` |
| 3 | `~/.codex-3` |
| 4 | `~/.codex-4` |

- Public index is 1-based. The lookup is `"${XCODEX_DIRS[@]:$1-1:1}"`, an array
  slice that is 0-based in **both** bash and zsh, which is why it is used instead
  of `${XCODEX_DIRS[$1]}` (zsh arrays are 1-based, bash 0-based).
- `XCODEX_DIRS` is the single source of truth; `install.sh` reads it by sourcing
  `xcodex.sh` in a subshell. Edit it to add/remove/relocate profiles. Consumers
  must read the list, never assume there are exactly two (or four).

---

## 3. CLI contract (read off `reference/xcodex/xcodex.sh`)

### `xcodex ls`

- Checked first: if `$1 = ls`, print the list and return 0 (extra args ignored).
- One line per entry, to **stdout**:
  `  <i>) <dir> [<exists|missing>, logged in: <label>]` or
  `  <i>) <dir> [<exists|missing>, not logged in]`.
- Login label comes from `_xcodex_label <dir>`:
  1. `python3 ~/.config/xcodex/xcodex.py identity <dir>` (stderr discarded); on
     exit 0 its stdout is the label.
  2. Else, if the dir exists and `CODEX_HOME=<dir> command codex login status`
     exits 0, the label is `Codex account (keyring)` (detects keyring-backed
     logins without reading the keyring).
  3. Else: not logged in.
- `ls` never creates directories.

### `xcodex <index> [codex args...]`

In order:

1. Validate index: empty or any non-digit → usage on stderr, return 1. Out of
   range (`< 1` or `> ${#XCODEX_DIRS[@]}`) → usage, return 1. Usage text lists
   the three forms plus the `ls` output, all on **stderr**.
2. `shift` the index; **every remaining argument is forwarded unchanged** (e.g.
   `xcodex 2 resume --last`, `xcodex 3 -m <model>`, `xcodex 4 login status`).
3. If the dir is missing, create it with `umask 077` (mode 700).
4. Compute `label` (as above) or `login required`; title is
   `xcodex <index> · <label>`.
5. Build injected config overrides, placed **before** user args (so a later
   user `-c` for the same key wins):

   | Injection | Condition | Purpose |
   |---|---|---|
   | `-c tui.status_line=["model-with-reasoning","git-branch","context-used","five-hour-limit","weekly-limit"]` | `XCODEX_STATUS_LINE` unset or not `0` — **not** TTY-gated | Codex's native footer items (Codex owns and refreshes the values) |
   | `-c tui.terminal_title=[]` | `XCODEX_TITLE` not `0` **and** stdout is a TTY | Stop Codex's own title updater overwriting the account title |
   | OSC title `\033]0;<title>\007` to stdout | same as above | Window title shows account |
   | `xcodex: account <i> · <label> · <dir>` banner to stderr | `XCODEX_ACCOUNT_BANNER` not `0` **and** stderr is a TTY | Launch banner |

   Nothing is written to any `config.toml`; overrides are per-run only.
6. Run `CODEX_HOME="$dir" command codex "${injected[@]}" "$@"`. `command`
   bypasses any function/alias named `codex`. `CODEX_HOME` is set only for that
   child, not exported into the shell.
7. If the title was set, clear it (`\033]0;\007`). Return codex's exit status.

### `xcodex-seed <index>`

- Validates the index the same way, then runs
  `python3 ~/.config/xcodex/xcodex.py seed "$HOME/.codex" <dir>`.
- Source is always `~/.codex`, so `xcodex-seed 1` fails ("is the source", exit 1).

### `xcodex.py` (credential-safe helper)

`identity <config-dir>` — prints a display label, exit 0; exit 1 if none:
- Parses `<dir>/auth.json` (any error → `{}`).
- Non-empty `OPENAI_API_KEY` → `OpenAI API key`.
- Else `tokens.id_token`: base64url-decodes the JWT **payload only** (no
  signature check — display only, never authorization) and returns `email`, else
  `name`, stripped to printable characters, max 160 chars.
- Else if `tokens.refresh_token` or `tokens.access_token` is present →
  `ChatGPT account`.
- Never prints, logs, or transmits any token.

`seed <src> <dst>` — copies reusable config only:
- Candidates: `AGENTS.md`, `config.toml`, `hooks.json`, `rules/`, `skills/`,
  `themes/`, plus `<src>/*.config.toml`. Nothing else is ever considered — not
  `auth.json`, sessions, history, state DBs, memories, logs, caches, or MCP
  OAuth credentials.
- Refuses if `src == dst` (after resolve) or `src` is missing. Creates `dst`
  with mode 700.
- Existing destination item → interactive `[y/N]` prompt ("merge into" for
  dirs, "overwrite" for files); EOF/Ctrl-C = No. So non-interactive runs skip
  every existing item.
- Directories merge via `copytree(dirs_exist_ok=True, symlinks=True)` (never
  deletes). Symlinks are recreated as symlinks; it refuses to replace an existing
  symlink or to put a file over a dir/symlink (or a dir over a file).
- Any copy exception → exit 1. Prints `copied or merged N shared item(s)`.
- Caveat: a copied `config.toml` may contain a secret you embedded by hand.

Any other argv → usage on stderr, exit 2.

---

## 4. Install and idempotency

Files must live at `~/.config/xcodex/`: both the rc source line and
`_xcodex_helper` hardcode `$HOME/.config/xcodex/...`, even though `install.sh`
itself locates siblings via its own directory.

`reference/xcodex/install.sh` (bash, `set -euo pipefail`):

1. Requires `python3` and `codex` on PATH, and `xcodex.sh`/`xcodex.py` next to
   it; `chmod +x install.sh xcodex.py`.
2. Reads `XCODEX_DIRS` via `dirs=$( . "$here/xcodex.sh"; printf '%s\n' "${XCODEX_DIRS[@]}" )`
   (subshell — no functions leak into the installer).
3. For each of `~/.zshrc`, `~/.bashrc` **that already exists** (it does not
   create rc files): if it contains `xcodex/xcodex.sh`, skip; else append
   ```sh
   [ -f "$HOME/.config/xcodex/xcodex.sh" ] && . "$HOME/.config/xcodex/xcodex.sh"
   ```
4. Creates any missing profile dir with `umask 077`. Never touches existing dirs.
5. Copies no credentials; the directory is portable to another machine.

Re-running is safe: the grep guard prevents duplicate rc lines, existing dirs
are left alone. After install: `exec "$SHELL"`, `xcodex ls`, `xcodex 2` (an empty
home starts Codex's normal login flow), optionally `xcodex-seed 2` (before or
after login; it cannot copy or replace a login).

---

## 5. Integrating with automation

Lessons recorded while wiring xcodex into an automated code-review runner.

**xcodex is a shell function, not a binary.** `spawn('xcodex', …)`,
`npm run` scripts, `executableOnPath('xcodex')`, cron, and non-interactive
`sh -c` cannot see it. Programs select a profile by setting `CODEX_HOME` in the
child's environment and spawning `codex`:

```ts
// review runner (TypeScript)
spawn('codex', args, { env: { ...process.env, CODEX_HOME: profile.home }, detached: true, ... });
```

From a shell, the equivalent of `xcodex 2 <args>` for a tool that spawns codex:
`CODEX_HOME=$HOME/.codex-2 <command>`.

**Resolve dirs from the same 1-based mapping.** The reference runner
hardcodes it (`index 1 → ~/.codex`, else `~/.codex-<i>`, indexes 1–4), with an
env override `CODEX_PROFILES` (default `1,2`; one or two distinct indexes;
malformed/duplicate/longer lists are refused before launch). It deliberately
does not inherit the caller's `CODEX_HOME`. Hardcoding drifts if someone edits
`XCODEX_DIRS` **(inference)**; a drift-free alternative is to read the list the
way `install.sh` does:
`bash -c '. "$HOME/.config/xcodex/xcodex.sh"; printf "%s\n" "${XCODEX_DIRS[@]}"'`.

**Do not copy the TTY cosmetics.** `-c tui.status_line=…` and
`-c tui.terminal_title=[]` are interactive-TUI cosmetics. A `codex exec --json`
run reading the event stream must not get them. Note the wrapper itself does
not TTY-gate the status-line injection, so `xcodex N exec …` still passes it —
another reason programs should spawn `codex` directly.

**Login probe without reading credentials.** `CODEX_HOME=<dir> codex login status`
exit code (the runner uses a 10 s timeout and kills the process group). Login
status does not prove quota and must not veto a real attempt. Spawn codex
`detached` and kill with `kill(-pid)`: the `codex` launcher execs a vendored
binary, and killing only the launcher left an orphan still burning tokens.

**Cheap availability ping (~2k tokens):**
`CODEX_HOME=<dir> codex exec --skip-git-repo-check -s read-only -m <model> --ephemeral - <<< "reply ok"`.
An exhausted profile answers `You've hit your usage limit … try again at <time>`.

**Fallback policy.**
- Switch to the next profile **only for a no-report outcome**: usage limit,
  auth expiry, upstream outage, crash, timeout, malformed/unparseable output, or
  a sandbox that blocked every read.
- A run that produced a parseable result is **spent, whatever it says**.
  Re-running a judgment on another account for a friendlier answer is
  "review shopping" and is forbidden.
- Bound it: the reference runner allows at most one replacement per role (two
  profiles), records every attempt (profile, `CODEX_HOME`, login state,
  artifacts under `profile-<index>/`), and mirrors the final attempt to the
  canonical output paths.
- Parse output before classifying it (a truncated `{` file is a no-report
  retry, not a spent judgment — a real bug found in that runner).
- Prefer the lowest-index logged-in profile with limits left; once one is
  exhausted, stay on the next until the published reset time passes.
- "Unavailable" means every configured profile refused; record each refusal
  verbatim.
- Check `xcodex ls` first: a `not logged in` profile is not a fallback. It dies
  in ~17 s with `401 Unauthorized: Missing bearer` — neither a timeout nor a
  usage limit. Logging a profile in is an owner action.

---

## 6. Verification checklist

Run in a new interactive shell after install (bash and zsh both).

```sh
bash -n ~/.config/xcodex/xcodex.sh && zsh -n ~/.config/xcodex/xcodex.sh
python3 -m py_compile ~/.config/xcodex/xcodex.py
type xcodex xcodex-seed               # both: shell function
grep -c 'xcodex/xcodex.sh' ~/.zshrc ~/.bashrc   # 1 each (for rc files that exist)
~/.config/xcodex/install.sh && grep -c 'xcodex/xcodex.sh' ~/.zshrc ~/.bashrc  # still 1: idempotent
xcodex ls                             # one line per XCODEX_DIRS entry, exit 0
xcodex; echo $?                       # usage on stderr, 1
xcodex 0; xcodex 5; xcodex abc        # each: usage, 1 (5 = out of range with 4 dirs)
xcodex 2 login status; echo $?        # passthrough; reflects ~/.codex-2 only
python3 ~/.config/xcodex/xcodex.py identity ~/.codex-4; echo $?  # label or exit 1; never a token
python3 ~/.config/xcodex/xcodex.py; echo $?   # usage, 2
xcodex-seed 1; echo $?                # "is the source", 1
```

Check env and argv plumbing with a stub `codex` (no network, no real account):

```sh
stub=$(mktemp -d); printf '#!/bin/sh\necho "CODEX_HOME=$CODEX_HOME"; printf "[%%s]\\n" "$@"\n' > "$stub/codex"; chmod +x "$stub/codex"
PATH="$stub:$PATH" xcodex 3 exec --json 'a b' | cat
# expect: CODEX_HOME=$HOME/.codex-3, [-c], [tui.status_line=[...]], [exec], [--json], [a b]
# and NO tui.terminal_title (stdout is a pipe) and no banner if stderr is not a TTY
# (verified in bash with the reference files under a temp HOME; zsh not tested here)
PATH="$stub:$PATH" XCODEX_STATUS_LINE=0 xcodex 3 x | cat   # expect only [x] after CODEX_HOME
```

To test install without touching the real home **(inference: everything keys
off `$HOME`)**: `HOME=$(mktemp -d)`, `touch $HOME/.bashrc`, copy the four files
to `$HOME/.config/xcodex/`, run `install.sh`, and check new dirs have mode 700
(`stat -c %a "$HOME/.codex-2"`).

For automation: assert the child env carries the right `CODEX_HOME`; a no-report
first attempt falls back; a report-producing first attempt does **not**; an
exhausted list yields an honest "unavailable" (these were the reference runner's
runner tests).

---

## 7. Security notes

- **Never read, print, copy, or log credential contents** (`auth.json`, tokens,
  keyring). Determine login state only via `xcodex ls`, `xcodex.py identity`
  (prints a label only), or `codex login status` exit code. Do not `cat` or
  `jq` `auth.json` to "check" anything.
- The JWT decode is cosmetic; Codex alone authenticates and refreshes.
- Directories are created mode 700; seeding never considers auth, sessions,
  history, DBs, memories, logs, caches, or MCP OAuth credentials.
- The reference directory is safe to share/copy precisely because it holds no
  credentials. Keep it that way.

---

## 8. Pitfalls

- Calling `xcodex` from a program/script — it is a function; set `CODEX_HOME`
  and spawn `codex`.
- Assuming index 1 is `~/.codex-1`: it is `~/.codex` (Codex's default home).
- Indexing `XCODEX_DIRS` with `[$i]` — off by one in one of bash/zsh; use the
  slice.
- Forgetting `command codex` if a user aliases/wraps `codex`.
- Placing injected `-c` after `"$@"` — would override the user's `-c`.
- Writing status/title into `config.toml` instead of per-run `-c` — mutates
  every account's config.
- Carrying `tui.*` overrides into `--json`/`exec` automation.
- Treating `not logged in` profiles as fallbacks (17 s 401), or re-trying an
  exhausted profile before its stated reset time (same refusal string).
- Falling back after a valid result (review shopping), or looping over every
  profile instead of a bounded retry.
- Inheriting the caller's `CODEX_HOME` in automation silently pins whatever
  account the caller happened to use; resolve explicitly.
- Expecting non-interactive `xcodex-seed` to overwrite: prompts read EOF as No.
- Leading-zero indexes: `[ -gt ]` compares decimally but the slice
  `$1-1` is bash arithmetic (octal for a leading `0`). With 4 dirs this is
  harmless (`02` → profile 2, `08` → out of range; checked in bash). With 8+
  dirs, `08`/`09` would hit an invalid-octal error **(inference)**. Pass plain
  integers.
- `resume --last` is per profile (separate session stores) and Codex also scopes
  it to the cwd unless `--all`.

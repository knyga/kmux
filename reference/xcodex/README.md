# xcodex — multiple Codex accounts on one machine

`xcodex` runs the installed Codex CLI against one of several isolated
`CODEX_HOME` directories. Each directory owns its own login, sessions, history,
configuration, skills, plugins, caches, memories, and local databases, so logging
one account in or out does not disturb another account.

Everything needed to replicate the wrapper lives here:

```text
~/.config/xcodex/
├── xcodex.sh     shell functions for Bash and Zsh
├── xcodex.py     local account-label and safe seeding helpers
├── install.sh    idempotent installer
└── README.md
```

## Commands

- `xcodex <index> [codex args...]` runs Codex with the selected home. Every
  remaining argument is forwarded unchanged, so commands such as
  `xcodex 2 resume --last`, `xcodex 3 -m gpt-5.6-sol`, and
  `xcodex 4 login status` work normally.
- `xcodex ls` lists each configured directory and its login identity. For a
  ChatGPT login, the label is decoded locally from the ID token in `auth.json`;
  no token is printed or sent anywhere. Keyring-backed logins are detected with
  `codex login status` and shown with a generic label.
- `xcodex-seed <index>` offers to copy reusable configuration from `~/.codex`:
  `AGENTS.md`, `config.toml`, profile `*.config.toml` files, `hooks.json`,
  `rules/`, `skills/`, and `themes/`. Existing directories are merged rather
  than deleted.

Seeding never considers `auth.json`, sessions, history, state databases,
memories, logs, caches, or MCP OAuth credentials. A copied `config.toml` is still
your configuration, so inspect it first if you manually embedded a third-party
secret there.

## First use

```sh
~/.config/xcodex/install.sh
exec "$SHELL"
xcodex ls
xcodex 2
xcodex-seed 2
```

An empty secondary home starts Codex's normal login flow. Run the seed before or
after login; it cannot copy or replace the login.

Edit `XCODEX_DIRS` in `xcodex.sh` to add, remove, or relocate accounts. The
shipped list is `~/.codex`, `~/.codex-2`, `~/.codex-3`, and `~/.codex-4`.

## Account identity and live status

Claude Code accepts an arbitrary status-line command; Codex intentionally uses a
native list of footer items instead. The wrapper therefore divides the display:

- The terminal/window title and a launch banner show `xcodex <index>` plus the
  account email (or a generic API-key/keyring label).
- Codex's native footer shows model + reasoning, git branch, context used,
  five-hour usage, and weekly usage. These values are owned and refreshed by
  Codex itself.

The footer and title are injected as per-run config overrides, leaving every
account's `config.toml` untouched. A later `-c` argument can override them. Set
`XCODEX_STATUS_LINE=0`, `XCODEX_TITLE=0`, or `XCODEX_ACCOUNT_BANNER=0` to disable
the corresponding wrapper behavior. Some terminals do not display window
titles; the native footer still works there.

## Notes

- This isolates account identity and Codex state, not the filesystem. All
  accounts still run as the same operating-system user.
- `resume --last` is naturally account-scoped because each home has its own
  session store. Codex also scopes `--last` to the working directory unless
  `--all` is supplied.
- The local JWT decode is cosmetic only. Codex remains solely responsible for
  authenticating and refreshing the session.
- Copy this whole directory to another machine and run `install.sh`; credentials
  are not part of the directory.

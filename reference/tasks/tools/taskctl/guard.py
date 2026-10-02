"""PreToolUse(Bash) hook, Claude Code and Codex alike: refuse hand-moved or hand-deleted task files.

Folder = status, and only the ``tasks`` CLI moves a file between status folders: it takes the mutex,
writes the lease, the branch, the worktree and the Progress line in one step. A ``git mv`` by hand
skips all of that and leaves a task that looks claimed (or closed) with nothing behind it.

The skill text says the same thing; this makes it deterministic. Reads the hook payload on stdin
(``{"tool_input": {"command": "..."}}``), exits 2 with the reason on stderr to block. Fails OPEN on
anything it cannot parse: a guard that eats a legitimate command is worse than one that misses.
Standalone on purpose (no package imports) so it starts fast on every Bash call.
"""

from __future__ import annotations

import json
import re
import shlex
import sys

STATUSES = ("todo", "in_progress", "human_action_required", "done", "cancelled")
TASK_PATH = re.compile(r"(?:^|/)tasks/(?:" + "|".join(STATUSES) + r")(?:/|$)")
SEPARATORS = {";", "&&", "||", "|", "&", "\n", "(", ")"}


def _segments(command: str) -> list[list[str]]:
    lex = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=";&|()")
    lex.whitespace_split = True
    out: list[list[str]] = [[]]
    for tok in lex:
        if tok in SEPARATORS or set(tok) <= set(";&|()"):
            out.append([])
        else:
            out[-1].append(tok)
    return [seg for seg in out if seg]


def _strip_prefix(seg: list[str]) -> list[str]:
    """Drop env assignments and wrappers (``FOO=1 sudo command git mv ...``)."""
    i = 0
    while i < len(seg) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i]) or seg[i] in ("sudo", "command", "env", "exec", "nohup")):
        i += 1
    return seg[i:]


def violation(command: str) -> str | None:
    if "tasks/" not in command:
        return None
    for seg in _segments(command):
        seg = _strip_prefix(seg)
        if not seg:
            continue
        if seg[0] == "git":
            rest = seg[1:]
            while rest and rest[0].startswith("-"):  # git -C dir / -c k=v
                rest = rest[2:] if rest[0] in ("-C", "-c") else rest[1:]
            if not rest or rest[0] not in ("mv", "rm"):
                continue
            verb, operands = f"git {rest[0]}", rest[1:]
        elif seg[0] in ("mv", "rm"):
            verb, operands = seg[0], seg[1:]
        else:
            continue
        hits = [op for op in operands if not op.startswith("-") and TASK_PATH.search(op)
                and not op.rstrip("/").endswith(".gitkeep")]
        if hits:
            return (f"refused: `{verb}` on {', '.join(hits)} moves or deletes a task file by hand. "
                    "Status changes go through the CLI only: `tools/tasks claim | park | close [--cancel]` "
                    "(contract: tasks/README.md). If the CLI itself is wedged, record it in "
                    "tasks/tooling-log.md and tell the user instead of moving files.")
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        command = (payload.get("tool_input") or {}).get("command")
        if not isinstance(command, str):
            return 0
        reason = violation(command)
    except Exception:  # fail open
        return 0
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

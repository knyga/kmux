---
name: solve-next-task
description: Claim the next task from tasks/ via `tools/tasks claim --json` and take it end to end — understand, plan, implement in the claim's worktree, verify, close — exactly ONE task. Use when asked to "solve the next task", "pick up a task", "work the queue", or when a task slug is handed over already claimed.
---

# solve-next-task

Claim → understand → plan → implement → verify → close. ONE task. Contract: `tasks/README.md`.
Selection is executed by the CLI, never reasoned about: **never pick a task by reading `tasks/`**.

## 0. Claim FIRST

Run `tools/tasks claim --json` (or `--slug <handle> --json` when the user named one) from the main
checkout before inspecting any candidate. Obey its output.

- exit 3 → nothing available: stop and say so.
- exit 4 → refused (unknown slug / live session holds it): report the reason. Do NOT retry with another slug.
- `mode: resume` → run `tools/tasks resume <slug>`, continue from its `NEXT:` line; re-run NO gate
  the task file already records as done.
- `mode: adopt` → BEFORE writing anything read the `## Progress` trail, `git log --oneline main..<branch>`,
  `git status --short` in the worktree. Continue on that branch by default; restart only if it is
  unusable, and record in `## Progress` what was discarded and why.
- Header plainly wrong against the rubric in `tasks/README.md` (type/priority/creator)? Fix it in a
  one-line commit first (pathspec = the task file only).

Prefix every later tracker call with `TASKS_SESSION=<session from the JSON>` (exports may not survive
between shell calls) so heartbeats, park and close find the lease. Heartbeat
(`tools/tasks claim --heartbeat`) at every phase boundary.

## 1. Understand

Read the task file fully. Run `tools/tasks outcomes <keyword>` over the subject BEFORE designing —
closed tasks record measured facts and dead ends; do not rediscover them. Write the plan as `## Items`
(add a `## Plan` if the shape is not obvious) and commit it before the first code commit.

## 2. Implement in the worktree

All code changes happen in the claim's `worktree` on branch `<slug>`, never in the shared checkout.
Task-file edits (`tasks/in_progress/NNNN-<slug>.md`) are the one exception: edit and commit them in the
main checkout with an explicit pathspec (`git commit -m "..." -- tasks/in_progress/NNNN-<slug>.md`).
Micro-commit each logical change. Never `git add -A` in the main checkout.

`type: bug`: write the failing regression test first. Do not edit a test that existed before the
branch unless the file lists it under `## Test changes` with a reason; if the test itself looks wrong,
park.

## 3. Checkpoint discipline

Append a `## Progress` line at every phase boundary AND before anything long-running, naming what was
started and where its output lands (`- YYYY-MM-DD started <what> → <log path>`). Run long commands
detached from a script file (`nohup bash script.sh > <log> 2>&1 &`), never from stdin, so a dropped
link cannot kill a ten-minute run. Poll the log; do not block the turn.

## 4. Capture at birth — same turn, by scope

| what you noticed | where it goes (immediately) |
|---|---|
| measured fact, seam that behaved differently, proven dead end | `## Outcome` of this task |
| in-scope deferral | `## Followups` of this task |
| out-of-scope bug or doc drift | `tools/tasks index --create <slug> --discovered-by <current-slug> [--type bug]` — do NOT fix inline |
| tooling gap | `tasks/tooling-log.md` — do NOT build inline |

A chat-only mention is lost and counts as a violation.

## 5. Blocked on a human

Credential, spend, irreversible product call: first read `tasks/policies.md` — if the owner already
answered this class, follow the answer and cite it in `## Decisions`. Otherwise finish every item that
does not depend on it, then `tools/tasks park <slug> --reason "<concrete action the human must take>"`
and stop. Never read or print a credential to get past it.

## 6. Verify

Run the commands in `tasks/gate.cmds` in the worktree, plus whatever the task names. Never mark an
item complete without proof; write the proof (command, result, numbers) into `## Outcome`. The
`Verdict:` line is mandatory before close.

## 7. Close or hand off

`tools/tasks close <slug>` — gates (items checked, Verdict present, Followups resolved), the merged
tree's `gate.cmds`, `--no-ff` landing on main, move to `done/`, retire branch/worktree/lease. Read any
refusal, fix, re-run; never bypass a gate (`--no-merge`, `--force-worktree`, editing `gate.cmds` are
not fixes). Do not push unless the user asked.

Stopping short? Append an exact handoff to `## Progress`:
`- YYYY-MM-DD NEXT: <next unchecked item>; never ran: <commands/gates not executed>` and commit it.

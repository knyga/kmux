<!-- tasks-kit:workflow -->
## Task workflow

Work items live in `tasks/<status>/NNNN-<slug>.md` (folder = status: `todo`, `in_progress`,
`human_action_required`, `done`, `cancelled`). The contract is [tasks/README.md](tasks/README.md); the
tool is `tools/tasks` (stdlib Python ≥ 3.11, package `tools/taskctl/`). Skills: `solve-next-task` (one
task end to end), `solve-next-task-loop` (coordinator; Claude: `/loop /solve-next-task-loop`, Codex:
`$solve-next-task-loop`), `file-tasks` (intake, no implementation).

- Direct requests are handled directly; do not claim an unrelated queue task for an ad hoc change.
- **Never pick a task by reading the folders.** `tools/tasks claim --json` selects and mutates in one
  locked step (resume > adopt > todo > stale parked; exit 0 claimed / 3 nothing / 4 refused) and hands
  back branch `<slug>` + worktree `.worktrees/<slug>`. Work there; only task-file commits go to the main
  checkout, always with an explicit pathspec. Never move or delete a task file by hand (a `PreToolUse`
  hook refuses `git mv`/`rm` on them).
- Pass the returned `TASKS_SESSION=<id>` on every tracker call; heartbeat at phase boundaries.
- Capture at birth, same turn: measured fact / dead end → `## Outcome`; in-scope deferral →
  `## Followups`; out-of-scope bug or doc drift → `tools/tasks index --create <slug> --discovered-by
  <current>`; tooling gap → `tasks/tooling-log.md`. A `## Progress` line before anything long-running;
  `NEXT:` handoff when stopping short.
- Blocked on a human: check `tasks/policies.md` for a standing answer, else finish independent items and
  `tools/tasks park <slug> --reason "<concrete action>"`. Parking is the sanctioned exit — never weaken
  a gate or a pinned test to get past one.
- `tools/tasks close <slug>` gates (items checked, `Verdict:` in Outcome, followups resolved, the
  merged tree passes `tasks/gate.cmds`) and lands with `git merge --no-ff`. Do not push unless asked.
- One task per subagent; never parallelize claims, closes or tracker mutations.
<!-- /tasks-kit:workflow -->

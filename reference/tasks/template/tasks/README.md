# tasks/ — the task store (contract for agents)

Markdown files, **folder = status**. Managed only through the `tasks` CLI (`tools/tasks`, package
`tools/taskctl/`, stdlib Python ≥ 3.11). Selection is executed, never reasoned about: **an agent never
picks a task by reading these folders** — it runs `tools/tasks claim --json` and obeys the output.

```
tasks/
  todo/  in_progress/  human_action_required/  done/  cancelled/   # each holds NNNN-<slug>.md
  README.md         # this contract
  gate.cmds         # the merged-tree verification `tasks close` runs (one command per line)
  policies.md       # the owner's standing answers: what an agent does instead of parking
  tooling-log.md    # dev-capability gaps noticed mid-work (append, never build inline)
  .leases/  .claim.lock/                                          # runtime, gitignored
```

## The loop this implements

Each stage ends by committing an artifact that triggers the next, and every gate between stages is a
**script**, not a promise:

```
intent (a task file in todo/)                         tools/tasks index --create
  → claim: lease + branch + worktree, one locked step  tools/tasks claim --json
  → plan + build in the worktree, Progress heartbeats  (skill: solve-next-task)
  → evidence in ## Outcome, Verdict line               (written the turn a fact is measured)
  → close: cheap gates, merged-tree gate, --no-ff land tools/tasks close
  → new intents born during the work                   tools/tasks index --create --discovered-by
```

A skill makes a rule likely; a hook or a CLI refusal makes it close to impossible. The rules that must
always hold are enforced by `tools/tasks` (claim, close, park refuse on their own) and by the
`PreToolUse` guard `tools/taskctl/guard.py` (refuses hand `git mv` / `rm` of task files, for Claude
Code and Codex alike). Everything else in this file is advisory and lives in the skills.

## Files

`NNNN-<slug>.md` — 4-digit index (short handle, `ls` is chronological) + kebab slug = **stable
identity**. Never rename a slug; files only move between folders, and only the CLI moves them.
Cross-reference with a status-free glob: `tasks/*/0042-some-slug.md`. Every handle resolver accepts
the index (`42`), the bare slug, or the whole filename.

Template (`tools/tasks index --create <slug>` writes it):

```
# Title

type: bug            # task | bug | idea | readback | chore | spike
priority: p1         # p0 drop-everything | p1 next | p2 normal | p3 someday
creator: user        # who WANTED it: user | agent | triage | <any kebab token>
discovered-by: <slug of the task that surfaced it>   # optional
blocked-until: 2026-10-01                            # optional gate (a date)
blocked-by: 0031-parent-task                         # optional gate (another task)

<goal, 1-3 sentences>

## Outcome
<!-- filled DURING the work, the same turn a fact is measured. Verdict mandatory before close. -->

## Items
- [ ] 1. ...

## Progress
<!-- dated one-liners: heartbeat + handoff note -->
```

Metadata lives in the **header region** (everything above the first `## `). Parsing **fails open**:
unknown value → warning on stderr + default (`type task`, `priority p2`, `creator user`). A typo never
removes work from the queue. Gates (`blocked-until` in the future, `blocked-by` not in `done/` or
`cancelled/`) also fail open — unparseable ⇒ not gated, warned. The picker skips gated tasks and
prints what it skipped.

### Rubric

| type | when |
|---|---|
| `bug` | something that worked, or was specified, behaves wrong |
| `task` | planned change with a known shape |
| `spike` | an investigation whose output is an answer, not shipped code |
| `readback` | a dated check that a shipped change did what it claimed (metric, log, cost) |
| `chore` | maintenance with no behaviour change |
| `idea` | not yet decided; may be cancelled with a reason |

`creator` is who wanted it, not who typed it: a task the user asked for is `creator: user` even when
an agent filed it. 90 % of a mature queue is agent-born (followups, readbacks, drift) — `creator`
keeps the user's own asks first in line.

### Sections

| section | rule |
|---|---|
| `## Outcome` | Durable findings, written the turn they are measured: numbers, the seam that behaved differently, **dead ends** (nobody re-runs an experiment written down as failed). Ends with one `Verdict:` line — mandatory for `close`, `--cancel` included. |
| `## Items` | Checkboxes. `close` refuses any unchecked `- [ ]`. |
| `## Progress` | Dated one-liners. Heartbeat, what started where (`- YYYY-MM-DD started <what> → <log>`), and `NEXT:` handoffs. |
| `## Followups` | Optional. In-scope deferrals. Each entry must be `[x]`, carry `promoted: tasks/*/NNNN-slug.md`, or `wontfix: <reason>` before close. |
| `## Decisions` | Optional. Choices made under `policies.md`, cited as `policy (tasks/policies.md § b): …`. |
| `## Hypotheses` | Optional, for spikes: each `H<n>` = claim → prediction → instrument → falsifier → `Verdict: supported \| refuted \| inconclusive \| untested — deferred to <NNNN-slug>`. A refuted hypothesis is a successful close. |
| `## Test changes` | `type: bug` only: every **pre-existing** test the fix edits, one line each with the reason. A bug fix must not weaken the test that pins the bug; new test files are always fine. |

## CLI

```
tools/tasks index                                  # index -> status -> slug (+ type/priority/creator, title)
tools/tasks index --create <slug> [--type t --priority p --creator c --discovered-by s --title "..."]
tools/tasks index --assign                         # give an index to files that arrived without one
tools/tasks claim [--slug <handle>] [--json]       # THE claim command (exit 0 claimed · 3 nothing · 4 refused)
tools/tasks claim --heartbeat                      # refresh this session's lease (TASKS_SESSION)
tools/tasks status [--stale]                       # every lease live/dead + age; --stale = adoptable only
tools/tasks resume [<handle>]                      # briefing for work this machine dropped
tools/tasks park <handle> --reason "<what a human must do>"
tools/tasks close <handle> [--cancel] [--dry-run] [--no-merge] [--force-worktree]
tools/tasks outcomes <keyword>                     # grep ## Outcome of done/ + cancelled/
tools/tasks loop-state session                     # the run's persisted TASKS_SESSION id (create once)
tools/tasks loop-state begin <slug> | record <slug> <status> "<note>" | report | reset
```

All mutation happens under one mutex (`tasks/.claim.lock/`, mkdir-atomic, owner pid inside, stale =
owner pid dead on this host). Every tracker commit uses an explicit pathspec, so other dirty files in
the checkout are never swept in. Tracker commits go to the **main checkout**, even when the CLI is run
from a worktree.

### claim — pool order is absolute

1. **RESUME** — this host's own work: a task whose lease's session pid is dead (evidence, not a clock),
   a task whose live lease belongs to *this* session (same `TASKS_SESSION`; a caller without one matches
   by the same long-lived process on this host — so a stalled iteration gets the same slug back), or a
   lease-less `in_progress/` task whose last `claimed by … on host=<host>` line names this host.
2. **ADOPT** — `in_progress/` tasks stale (no activity 24 h: newest of last Progress date, file commit
   date, lease heartbeat) and unleased (lease absent or dead).
3. `todo/`.
4. Stale `human_action_required/` — last, on purpose.

Within a pool: priority `p0<p1<p2<p3` → type `bug > task > spike > readback > chore > idea` → creator
(`user` first, then alphabetical) → age (older first). Gates apply to every pool except RESUME.
`--slug` claims that exact task; refused (exit 4) if another live session holds it.

On success: file moved to `in_progress/`, Progress line
`- <date> claimed by <session> on host=<host> (mode=new|resume|adopt|slug)`, commit, branch `<slug>`
(from `main`, reused if present) + worktree `.worktrees/<slug>` (reused if present), lease written.
Output: `{slug, index, branch, worktree, mode, meta:{type,priority,creator,title}, file, session}`.

Lease `tasks/.leases/<slug>.json`: `session` (env `TASKS_SESSION` is honoured so heartbeats find it),
`pid` (the session's long-lived pid — env `TASKS_PID` overrides the ancestor walk), `pidStart` (so a
recycled pid cannot impersonate it), `host`, `branch`, `worktree`, `heartbeatAt`. Live: same host ⇒ pid
alive AND `pidStart` matches within ±2 s; other host ⇒ heartbeat younger than `TASK_LEASE_MINUTES` (60).

### close — stops at the first refusal, moves nothing

1. Cheap gates (all reported at once): `## Outcome` has a `Verdict:` line (mandatory, `--cancel`
   included); for `done` also no unchecked `- [ ]` under `## Items` and every `## Followups` entry
   resolved; when landing, the main checkout has nothing staged and is on `main`; the task worktree has
   no uncommitted changes (override with `--force-worktree`, which discards them on retire).
2. Expensive gate (skipped by `--cancel` / `--no-merge`): throwaway worktree at `main`, `git merge
   --no-commit --no-ff <slug>`, run every command in **`tasks/gate.cmds`** (read from the main checkout,
   never the branch, so a task cannot relax the gate that judges it; env `TASKS_GATE_CMDS`,
   `;;`-separated, overrides). A relative tool path the fresh worktree lacks (`.venv/bin/…`,
   `node_modules/.bin/…`) runs from the main checkout. No commands configured ⇒ close lands with a
   printed `WARNING … NOT verified` — fill `gate.cmds`.
3. Land: `git merge --no-ff <slug>` in the main checkout. Conflict ⇒ merge aborted, refused, nothing moved.
4. Move to `done/` (or `cancelled/`), Progress line, commit with pathspec.
5. Retire: `git worktree remove`, `git branch -d` (`-D` only under `--cancel`), drop lease.

Exit codes: 0 ok · 2 refused by a gate or the merge · 3 nothing to claim · 4 unknown handle / held by
another live session / already closed · 1 internal (a git command failed; message on stderr).

## Capture at birth (same turn, by scope)

| what you noticed | where it goes, immediately |
|---|---|
| measured fact, seam that behaved differently, proven dead end | `## Outcome` of the task you hold |
| in-scope deferral | `## Followups` |
| out-of-scope bug or doc drift | `tools/tasks index --create <slug> --discovered-by <current>`; never fix inline |
| tooling gap | `tasks/tooling-log.md`; never build inline |
| blocked on a human (credential, spend, irreversible product call) | check `tasks/policies.md` first; then finish independent items and `tools/tasks park <slug> --reason "<concrete action>"` |

A chat-only mention is lost. Before anything long-running, append a `## Progress` line naming what
started and where its output lands; when stopping short, `NEXT: <exact next unchecked item and what
was never run>`.

## Parking is the sanctioned exit

When a task cannot be done honestly — the spec and the tests disagree, the fix needs a credential, the
only options are irreversible — park it with the concrete human action. Never satisfy a gate by
weakening it (editing a pinned test, emptying `gate.cmds`, pasting a self-review where an independent
one was owed). An explicit "this is blocked" exit is what keeps an agent from gaming the verifier.

## Automation

Programs drive the loop by spawning `claude -p "/solve-next-task-loop"` or `codex exec
'$solve-next-task-loop …'` directly. Every run keeps one `TASKS_SESSION` (`tools/tasks loop-state
session`) so a restarted coordinator resumes its own stalled task instead of treating it as foreign.
Fall back to another account only when a run produced **no result** (usage limit, auth failure, crash,
timeout) — never re-run a completed judgment to get a different answer.

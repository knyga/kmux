---
name: solve-next-task-loop
description: Work sequentially through the tasks/ queue with persistent session identity, attempt limits, and tracker-verified outcomes. Use when asked to keep solving tasks or work through multiple queued tasks.
---

# Work through the queue

Use the existing `tools/tasks loop-state` implementation and the sibling [solve-next-task skill](../solve-next-task/SKILL.md). Run one task at a time in this Codex session; no scheduler, model alias, or delegation is required. Read `AGENTS.md` and `tasks/README.md` first.

## Establish the run

Run `tools/tasks loop-state report` in the main checkout to inspect prior totals and attempts, then `tools/tasks loop-state session` to obtain the persisted run ID. Supply it as `TASKS_SESSION` on every tracker call, including calls across separate shell tools or context compaction. Do not invent an ID or reset state unless requested. Do not share a running coordinator's session with a second concurrent loop.

Honor user limits and the CLI knobs: `SOLVE_LOOP_MAX_ATTEMPTS` defaults to 2 per slug, `SOLVE_LOOP_MAX_STALLS` to 3 consecutive stalls, `SOLVE_LOOP_MAX_TASKS` to 0 (unlimited settled tasks). Carry configured values on each applicable tracker call. Persisted totals are cumulative: if the user requests N additional tasks, track a baseline and stop after N new settlements rather than treating N as the historical total.

## Each iteration

1. Claim with `tools/tasks claim --json` using the run session. Exit 3: report totals and stop. Exit 4: report refusal and stop. Diagnose other errors without starting a second claim in parallel.
2. Run `tools/tasks loop-state begin <slug>`. If `shouldPark` is true, park with a concrete reason including the exhausted attempt budget and what needs intervention; record `parked` with `tools/tasks loop-state record`, then honor its decision. Do not spend another attempt on implementation.
3. Execute the single-task skill with the complete claim result as an already-claimed handoff, skipping its claim command. Keep its worktree, checkpoint, evidence, and closure rules. Finish one task before claiming another.
4. Verify the canonical task's actual folder in the main checkout: `done` → `done`; `human_action_required` → `parked`; `cancelled` → `cancelled`; `in_progress` → `stalled`. A missing file or an unexpected status needs investigation, not a fabricated success. Do not count the narrative report as evidence of closure.
5. Run `tools/tasks loop-state record <slug> <status> "<brief evidence-based note>"`. Honor `decision: stop` and the user's limits. A first stall is not automatically parked; when continuation is allowed the next claim resumes the same task, bounded by the attempt budget.
6. Give a concise update with task handle, status, result, and returned totals. Continue only within the requested scope and limits.

On interruption, preserve the active task's `NEXT:` before stopping and report where to resume. Never reset counters or bypass completion gates to keep a run going.

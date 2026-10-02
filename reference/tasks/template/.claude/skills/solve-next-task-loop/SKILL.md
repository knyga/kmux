---
name: solve-next-task-loop
description: Coordinator step for the task queue — claims exactly ONE task via `tools/tasks claim --json`, delegates the whole task to a single subagent, verifies the result from the tracker folders and records it in `tools/tasks loop-state`. Designed to be driven repeatedly by `/loop /solve-next-task-loop`. Use for "work through the queue", "run the solve loop", "keep solving tasks".
---

# solve-next-task-loop

Solves exactly ONE task per invocation, delegating implementation to a subagent. Driven by
`/loop /solve-next-task-loop`. **CONTEXT DISCIPLINE IS THE POINT**: the coordinator never reads a task
file, a diff or a log into its own context — one line per task. Everything verbose lives in the subagent.

Knobs (env): `SOLVE_LOOP_MAX_ATTEMPTS=2` (per slug), `SOLVE_LOOP_MAX_STALLS=3` (consecutive),
`SOLVE_LOOP_MAX_TASKS=0` (settled tasks per run; 0 = unlimited).

## Steps

0. Restarting a run? `tools/tasks loop-state report` to see totals so far. Only `loop-state reset`
   when the user asks for it.
1. Claim HERE, not in the subagent, with the run's session id on every tracker call:
   `RUN=$(tools/tasks loop-state session)` then `TASKS_SESSION=$RUN tools/tasks claim --json`.
   The id is persisted in `.solve-loop/state.json`, so every `/loop` turn — even after your context was
   lost — claims as the SAME identity; never invent an id by hand (a new id makes your own stalled task
   look foreign). Reuse `$RUN` verbatim on every later `tools/tasks` call and in the subagent brief.
   Exit 3 → print the totals from `loop-state report`, end the loop. Exit 4 → report the reason, end.
   Keep `slug`, `branch`, `worktree`, `mode`, `meta.priority`, `meta.type` from the JSON.
2. `tools/tasks loop-state begin <slug>`. If `shouldPark` is true →
   `tools/tasks park <slug> --reason "attempt budget exhausted (SOLVE_LOOP_MAX_ATTEMPTS)"`, then
   `tools/tasks loop-state record <slug> parked "attempt budget exhausted"`, spend nothing else, and
   report (step 6).
3. Spawn exactly ONE subagent (Agent tool, general-purpose, the most capable model available — it owns
   a whole task end to end) with the brief below, placeholders filled. Never two concurrently. Wait.
4. Verify from the TRACKER, not from the subagent's words: which folder holds
   `tasks/*/NNNN-<slug>.md` now? `done/` → done · `human_action_required/` → parked · `cancelled/` →
   cancelled · `in_progress/` → stalled.
5. `tools/tasks loop-state record <slug> <status> "<one-clause note from the subagent's report>"`.
   Honour `decision`: `stop` → say why and end the loop. Do NOT park on a first stall; the next
   invocation's `tools/tasks claim` hands the same slug back (mode `resume`: the lease is this
   session's, so it sits in the RESUME pool ahead of everything else) with its `## Progress` handoff.
6. Report exactly one line:
   `<slug> — <priority> <type> — <status> — <one clause> (run: N✓ N⏸ N✗)`
   where ✓ = done, ⏸ = parked, ✗ = stalled + cancelled, from the `totals` in the record output.

## Subagent brief (verbatim, placeholders filled)

> You own task `<slug>`. It is already claimed for you — branch `<branch>`, worktree `<worktree>`,
> mode `<mode>`. Do NOT run the claim command. Prefix every `tools/tasks` call with
> `TASKS_SESSION=<run-id>` (the same id as the claim) so heartbeats, park and close find your lease.
> Read `.claude/skills/solve-next-task/SKILL.md` and execute steps 1-7, skipping step 0.
> Invoke skills through the Skill tool; slash commands do not work in your context.
> All work happens in `<worktree>`, never in the main checkout — except task-file commits.
> You cannot ask the user anything. If you hit a decision only a human can make, check
> `tasks/policies.md`, do every item that does not depend on it, then park the task and stop.
> Never guess past it.
> Keep your own context alive: delegate verbose operations (test runs, log triage, wide searches) to
> nested subagents, micro-commit, and append a `## Progress` line as you go — including one when you stop.
> Return at most 10 lines: final status, what landed, what you verified and how, and anything the
> user must decide.

## Never

- Read the task file, the diff, or a log yourself. Ask the tracker (`tools/tasks index`, folder location).
- Run two subagents, two claims, or two closes concurrently.
- Reset loop state or bypass a gate on your own initiative.

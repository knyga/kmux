---
name: solve-next-task
description: Claim and complete exactly one queued task from tasks/, including a specified task handle or an already-claimed handoff, using the tools/tasks CLI and its worktree lifecycle. Use for requests to solve the next task or pick up one queued task.
---

# Solve one task

Read root `AGENTS.md` and `tasks/README.md`. Paths in this skill are repository-relative unless stated otherwise. The task CLI owns selection and lifecycle; do not rank candidate task files yourself.

## Claim or accept a handoff

From the main checkout run `tools/tasks claim --json`, or `tools/tasks claim --slug <handle> --json` when the user specified a task. Do this before inspecting candidates. Exit 3 means no eligible work: report and stop. Exit 4 means refusal: report the reason without trying another task. Other failures need diagnosis, not a guessed claim result.

An already-claimed handoff must include `slug`, `branch`, `worktree`, `mode`, `file`, and `session`; use those values without claiming again. Retain the absolute main checkout and CLI paths. Prefix every subsequent tracker command with `TASKS_SESSION=<returned-session>`; exports in one shell call may not survive the next. Heartbeat at phase boundaries with `tools/tasks claim --heartbeat`.

For `resume`, run `tools/tasks resume <slug>` and follow the recorded `NEXT:`. Reuse recorded evidence unless code, inputs, or the environment have changed enough to invalidate it. For `adopt`, first read the Progress trail, branch history (`git log --oneline main..<branch>`), and worktree status; preserve useful existing work. Do not reset or discard it merely to start fresh.

## Understand and implement

Read the claimed task fully and search prior results with `tools/tasks outcomes <keyword>`. Derive acceptance checks from the task's Items. Correct clearly wrong metadata with a tracker-file-only commit if needed. Commit the plan (Items) before the first code commit.

Implement on the returned branch in the returned worktree. A fresh worktree lacks ignored files (`.venv`, `node_modules`, data); set them up deliberately rather than pointing tools at the main checkout by accident. Commit logical code changes with explicit paths. Edit and commit the canonical task file in the main checkout, even when a stale copy exists in the worktree. Preserve unrelated staged/unstaged changes; never use blanket staging.

For `type: bug`, write the failing regression test first, and do not edit a test that existed before the branch unless the task file lists it under `## Test changes` with a reason; if the test itself looks wrong, park.

At phase boundaries and before long commands, append dated Progress notes naming the operation and log/artifact paths. Use a persistent tool session or a detached script file with a log for long jobs; poll and report progress. Record facts and dead ends in Outcome as measured, not just in chat. Put in-scope deferrals in Followups; create separate tasks for out-of-scope discoveries with `tools/tasks index --create <slug> --discovered-by <current-slug>`. Tooling gaps go in `tasks/tooling-log.md`.

## Verify and settle

Run the commands in `tasks/gate.cmds` plus task-specific acceptance checks; record commands, results, skips, and artifacts in Outcome. Mark Items complete only with evidence, resolve each Followups entry per the contract, and include a `Verdict:` line.

Run `tools/tasks close <slug>` to validate and land through the existing gates. This performs a local merge and retires the branch/worktree. Fix in-scope refusals and retry; do not use gate overrides, `--force-worktree`, `--no-merge` or edits to `tasks/gate.cmds` as shortcuts. If unrelated staged work blocks landing, preserve it and explain the concrete blocker. Do not push or publish unless requested.

If credentials, spend approval, or a product decision are genuinely missing, check `tasks/policies.md` for a standing answer first; otherwise finish independent items, then `tools/tasks park <slug> --reason "<concrete required action>"`. Do not treat elapsed time as approval. If stopping with work still in progress, commit a dated `NEXT: <exact next item>; never ran: <checks>` handoff. A technical interruption alone does not mean a task needs human action.

Report the task handle, actual tracker status, delivered result, verification, and any remaining blocker. Stop after this one task; the loop skill handles repeated work.

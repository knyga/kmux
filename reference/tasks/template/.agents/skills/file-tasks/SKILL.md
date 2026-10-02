---
name: file-tasks
description: Turn a request, a bug report, a review finding or a list of ideas into task files in tasks/todo/ via `tools/tasks index --create` — scoped, deduplicated, ranked by the rubric — without implementing anything. Use for "file a task", "add this to the queue", "make tasks from this", "plan this as tasks".
---

# file-tasks

The intake stage of the loop: an ask becomes a committed task file that `tools/tasks claim` can serve.
Triage only — **do not implement** what you file. Contract: `tasks/README.md`.

1. **Split by outcome.** One task = one verifiable result an agent can land in one sitting (the median
   task closes in about an hour). Anything bigger becomes several tasks chained with `blocked-by:`.
2. **Deduplicate before filing.** `tools/tasks index` for open work and `tools/tasks outcomes <keyword>`
   for closed work. An open task that already covers it → append the new signal to that file's goal or
   `## Items` (commit with its pathspec) instead of filing a twin. A closed task whose Outcome says it
   was a dead end → cite it in the new task, do not silently re-file.
3. **Create through the CLI only** (it assigns the index under the mutex and commits):
   `tools/tasks index --create <kebab-slug> --type <t> --priority <p> --creator <c> --title "<title>"`
   - `creator: user` when the user asked for it, even though you typed it; `agent` for your own finds;
     add `--discovered-by <slug>` when another task surfaced it.
   - `priority`: p0 only for broken-in-production; p1 reproducible user-facing defect or the user's
     next ask; p2 normal; p3 someday.
   - `type: spike` when the honest shape is hypothesis → experiment → verdict; seed `## Hypotheses`.
4. **Fill the stub** in the main checkout (one commit, pathspec = the file): a 1–3 sentence goal that
   says why, `## Items` as checkable acceptance criteria (each one provable by a command or a number),
   gates (`blocked-until:` / `blocked-by:`) where a fact must exist first.
5. Report one line per task filed: `NNNN-<slug> — <priority> <type> — <title>`.

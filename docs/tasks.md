# tasks — build spec

A file-based task queue plus the skills that drain it: the **AI SDLC loop**. Unlike kmux, xclaude and
xcodex it is not installed in `$HOME`. It goes **into a project repository**, gets committed there, and
every agent that opens the repo (Claude Code or Codex) gets the same queue, contract and skills.

| Piece | Lives at (in the target repo) | Source in this kit |
|---|---|---|
| The CLI `tasks` (stdlib Python ≥ 3.11) | `tools/tasks` + `tools/taskctl/*.py` | `reference/tasks/tools/` |
| The store and its contract | `tasks/{todo,in_progress,human_action_required,done,cancelled}/`, `tasks/README.md` | `reference/tasks/template/tasks/` |
| The merged-tree gate | `tasks/gate.cmds` | same |
| Standing answers (instead of parking) | `tasks/policies.md` | same |
| Tooling gaps | `tasks/tooling-log.md` | same |
| Claude skills | `.claude/skills/{solve-next-task,solve-next-task-loop,file-tasks}/` | `reference/tasks/template/.claude/` |
| Codex skills | `.agents/skills/{solve-next-task,solve-next-task-loop,file-tasks}/` | `reference/tasks/template/.agents/` |
| Guard hook (Claude + Codex) | `tools/taskctl/guard.py`, wired in `.claude/settings.json` and `.codex/hooks.json` | `reference/tasks/tools/taskctl/guard.py` |
| Agent entry points | a `## Task workflow` section in `AGENTS.md` (and `CLAUDE.md`) | `reference/tasks/snippets/task-workflow.md` |

Installer: `reference/tasks/install.sh [--dry-run] <target-repo>`.

## 1. The idea

Code is no longer the bottleneck. The bottleneck is everything around the build step — deciding
what to do, keeping state across sessions, verifying, landing, and remembering what was learned — and
an agent left to hold those in its own context drops them. So the loop externalizes all of it into
committed files and makes each transition a command:

```
intent        a task file in tasks/todo/                       tools/tasks index --create   (skill: file-tasks)
claim         lease + branch + worktree, one locked step       tools/tasks claim --json
build         plan as ## Items, code in .worktrees/<slug>,     (skill: solve-next-task)
              ## Progress heartbeats, facts into ## Outcome
gate          items checked, Verdict, followups resolved,      tools/tasks close
              gate.cmds green on main+branch merged
land          git merge --no-ff, file to done/, worktree gone  (same command)
new intents   bugs/drift found on the way, filed not fixed     tools/tasks index --create --discovered-by
```

Seven rules carry it. Each one came from a failure seen in the source repos:

1. **Folder = status, and only the CLI moves files.** No status field to drift from reality. A hand
   `git mv` skips the lease, branch, worktree and Progress line, so a hook refuses it.
2. **Selection is executed, never reasoned about.** An agent that reads `todo/` and picks one races
   other agents and argues itself into the interesting task. `tools/tasks claim --json` ranks
   (priority → type → creator=user first → age) and mutates under one mutex.
3. **One task, one branch, one worktree.** Parallel agents never share a checkout. Only task-file
   commits touch the main checkout, always with an explicit pathspec.
4. **Liveness is evidence, not a clock.** A lease records the pid and its start time. A dead pid
   frees the task at once, and a live session gets its own stalled task back (RESUME pool) rather
   than having it adopted by someone else.
5. **Capture at birth.** A measured fact goes in `## Outcome`, a deferral in `## Followups`, an
   out-of-scope bug in a new task, a tooling gap in `tooling-log.md`, all in the same turn. A
   chat-only mention is lost. Before designing, `tools/tasks outcomes <kw>` reads back what closed
   tasks measured, so dead ends are not re-run.
6. **Close is a gate, not a promise.** `Verdict:` is required. So are no unchecked items, resolved
   followups, and a green `tasks/gate.cmds` on the *merged* tree, read from main so a branch cannot
   relax its own gate. Close then lands with `--no-ff`.
7. **Parking is the sanctioned exit.** A task that needs a credential, a payment or an irreversible
   decision parks with the concrete human action. A spec that conflicts with its tests parks too.
   Weakening a gate or a pinned test is never the exit. (Models given a writable verifier cheat at
   it about half the time; an explicit "this is blocked" exit cuts that sharply — ImpossibleBench,
   arXiv 2510.20270.) `policies.md` holds the owner's standing answers, so tasks do not park on a
   question the owner already answered.

**Advisory vs deterministic.** A skill makes a rule likely; a hook or a CLI refusal makes it close to
impossible. The kit enforces deterministically what must always hold: claim, close and park refuse
on their own, and the guard hook blocks hand moves. Everything else is skill text. When a rule keeps
getting broken, move it from the skill into the CLI or a hook. Don't add more prose.

**Context discipline.** The loop coordinator (`solve-next-task-loop`) claims one task, hands the whole
task to one subagent, and checks the result from the folder the file ended up in, never from the
subagent's report. It reports one line per task. That is how it runs for hours without its own context
filling up.

### Provenance

The CLI and skills are a port of a private project's `taskctl` CLI (about 1.9k LOC, 69 tests) and its
`solve-next-task*` skills for Claude Code and Codex. That CLI is itself a distilled rewrite of a larger
in-house tracker that closed hundreds of tasks a week at a median claim→land time of about 1 h.
Changes from the source port:
`tasks/gate.cmds` replaces the hardcoded `ruff` + `pytest` gate, the CLI is vendored under `tools/`
with a launcher (no `pip install`), the guard hook is new, and the `file-tasks` intake skill is new.

## 2. CLI contract

The installed `tasks/README.md` is the full contract, and an agent working in the target repo reads
that file. In summary:

```
tools/tasks index [--create <slug> --type --priority --creator --discovered-by --title] [--assign]
tools/tasks claim [--slug <h>] [--json] | --heartbeat      exit 0 claimed · 3 nothing · 4 refused
tools/tasks status [--stale] | resume [<h>] | outcomes <kw>
tools/tasks park <h> --reason "<what a human must do>"
tools/tasks close <h> [--cancel] [--dry-run] [--no-merge] [--force-worktree]   exit 2 refused, nothing moved
tools/tasks loop-state session | begin <slug> | record <slug> <status> "<note>" | report | reset
```

Env: `TASKS_SESSION` (identity; pass it on every call), `TASKS_PID`, `TASKS_GATE_CMDS` (`;;`-separated,
overrides `gate.cmds`), `TASKS_MAIN_BRANCH`, `TASK_LEASE_MINUTES` (60), `TASKS_PYTHON` (launcher),
`SOLVE_LOOP_MAX_ATTEMPTS` (2), `SOLVE_LOOP_MAX_STALLS` (3), `SOLVE_LOOP_MAX_TASKS` (0 = unlimited).

Runtime state, gitignored: `tasks/.leases/`, `tasks/.claim.lock/`, `.solve-loop/`, `.worktrees/`,
`tools/taskctl/__pycache__/` (the launcher also sets `PYTHONDONTWRITEBYTECODE=1`).

## 3. Install procedure

Target = the project repository the user names. If they named none, ask; never default to this kit
repo. This kit is a build reference, not a project.

1. **Prerequisites:** `git`, `python3` ≥ 3.11, a repository with a `main` (or `master`) branch and at
   least one commit. Report anything missing.
2. **Existing store?** If `<target>/tasks/README.md` exists and is not this kit's contract, the
   project runs its own tracker (e.g. an npm `tasks:*` script suite). Stop and report. The installer
   refuses this case on its own.
3. **Dry run, then install:**
   ```sh
   <kit>/reference/tasks/install.sh --dry-run <target>
   <kit>/reference/tasks/install.sh <target>
   ```
   The installer follows AGENTS.md rule 1 and backs up every shared file it touches into
   `~/.config-backups/tasks-<UTC>/` with a `MANIFEST.txt`. It never overwrites a template the
   project has edited, and it replaces kit-owned code (`tools/tasks`, `tools/taskctl/`) only after a
   backup. Hook config is merged as JSON, so existing `settings.json` / `hooks.json` keys survive.
4. **Fill `tasks/gate.cmds`** with the project's real lint and test commands, read off its CI config,
   `package.json`, `Makefile` or `pyproject.toml`. Run each one in the main checkout first: a gate
   that is red on `main` blocks every close. If the project has no tests, say so in the report and
   leave the gate empty. Do not invent a gate that passes trivially.
5. **Commit on main** with the pathspec the installer prints. Claim creates worktrees from `main`, so
   until the kit is committed there, a worktree has no `tools/tasks`. Committing in the user's project
   is part of the install they asked for. Pushing is not.
6. **Seed (optional):** if the user gave work items, file them with the `file-tasks` skill
   (`creator: user`).

Codex hooks: `.codex/hooks.json` only runs once the user has trusted the project's hooks in Codex.
Report this; don't work around it. Without it, the skills still carry the rule as advisory text.

## 4. Verification checklist

Run in the target repo after the install commit. Steps 4–9 mutate the tracker and git, so run
them in a **throwaway clone** (`git clone <target> /tmp/tasks-verify`), never in the user's checkout.

```sh
bash -n tools/tasks && python3 -c 'import ast,sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]' tools/taskctl/*.py   # 1. syntax
tools/tasks --help >/dev/null && tools/tasks index; echo $?          # 2. runs; 0
<kit>/reference/tasks/install.sh .                                   # 3. "nothing to change"; your edited gate.cmds listed as kept
grep -c 'tools/taskctl/guard.py' .claude/settings.json .codex/hooks.json   # 1 each
# --- in the throwaway clone from here on
export TASKS_SESSION=verify-$$
tools/tasks index --create verify-kit --title "Verify kit"           # 4. created tasks/todo/NNNN-verify-kit.md
tools/tasks claim --slug verify-kit --json                           # 5. mode slug, worktree .worktrees/verify-kit
tools/tasks claim --json; echo $?                                    # 6. same slug again (mode resume), never a 2nd task
tools/tasks close verify-kit; echo $?                                # 7. 2: no Verdict, unchecked item; nothing moved
# check the item, add "Verdict: verified." under ## Outcome, commit that file (pathspec), commit
# one file in the worktree, then:
tools/tasks close verify-kit                                         # 8. gate passed (or WARNING if gate empty), merged, done/
echo '{"tool_input":{"command":"git mv tasks/done/x.md tasks/todo/"}}' \
  | python3 tools/taskctl/guard.py; echo $?                          # 9. refusal text, 2
echo '{"tool_input":{"command":"ls tasks/todo"}}' | python3 tools/taskctl/guard.py; echo $?   # 0
```

The kit's own suite covers the CLI and the guard, 88 tests (69 from the source port plus the gate-file and
guard tests). It needs pytest:

```sh
cd <kit>/reference/tasks && PYTHONPATH="$PWD/tools:$PWD/tests" python3 -m pytest -q tests   # 88 passed
```

## 5. Driving the loop

| | Claude Code | Codex |
|---|---|---|
| one task | `/solve-next-task` (or `… 42`) | `$solve-next-task` |
| drain the queue | `/loop /solve-next-task-loop` | `$solve-next-task-loop work through up to 3 tasks` |
| file work | `/file-tasks <what>` | `$file-tasks <what>` |
| headless | `claude -p "/solve-next-task-loop"` | `codex exec '$solve-next-task-loop …'` |

kmux keeps one tmux session per repo, so `kmux` in the target repo followed by
`/loop /solve-next-task-loop` gives a loop that survives a dropped SSH link. With xclaude/xcodex, a run
that ends with **no result** (usage limit, auth failure, crash) may be retried on the next profile
with the same `TASKS_SESSION`, and the RESUME pool hands the same task back. A completed judgment is
never re-run on another account (see AGENTS.md § For automation).

## 6. Layers not shipped (from the larger source tracker, adopt when the queue is big enough to need them)

Each layer below was built there in response to a measured failure. The kit leaves them out because
each one is project-specific. Add one once the failure shows up, as a CLI refusal or a hook, not as
more skill prose.

- **Independent review gate.** A second model reviews the plan before code and the diff before
  close. Its findings go in `## … review` sections, and close refuses when a section is missing.
  Lesson: a review gate that a heading alone can satisfy gets satisfied by a pasted self-review
  (a sizeable share of reviewed closes). Record "reviewer unavailable" with the error text, and file
  a rerun task.
- **Protected tests as a hook.** On a `type: bug` branch, refuse edits to a test file that existed at
  the merge-base unless `## Test changes` lists it with a reason. The kit has this rule only in the
  skill text.
- **Policy-checked park.** `park` parses a machine block in `policies.md` and refuses a reason that
  falls in a class the owner already pre-approved, e.g. spend under $2 or a reversible product default.
- **Blocked folders** (`todo__blocked/`, `in_progress__blocked/`) for work waiting on a fact rather
  than on a human. The kit uses the `blocked-until:` / `blocked-by:` header gates instead.
- **Bug-class registry** (`tasks/classes.md`): at the second repeat of a bug class, a local patch is
  forbidden by default and a systemic mechanism is required (in practice every class closed only via
  a mechanism, after several patch repeats).
- **Unattended launcher.** A cron/systemd one-shot running `claude -p` with rails: a stop file, a
  `flock`, a run-id reaper, a spend latch over a cost ledger, a soft and hard deadline, and
  `--max-budget-usd`. Arming a schedule is the
  owner's call.
- **Readbacks.** A shipped change that claims an effect files a dated `type: readback` task
  (`blocked-until:` its date) to check the claim against real data.

## 7. Pitfalls

- **A fresh worktree lacks ignored files** (`.venv`, `node_modules`, data). Tests in the worktree, and
  the gate's throwaway merge worktree, see only tracked files. The gate runs relative tool paths it
  can't find (e.g. `.venv/bin/pytest`) from the main checkout. Anything else the tests read must be
  set up on purpose, e.g. a worktree-local venv or read-only symlinks. In the source project, a Python editable
  install pointing at main made worktree tests import main's code, which is why the gate prepends
  `<worktree>/src` to `PYTHONPATH` when `src/` exists.
- **`TASKS_SESSION` must ride on every call.** Shell exports don't survive between tool calls. A new
  id makes your own stalled task look foreign.
- **Don't test the install with `claim`/`close` in the user's checkout.** Both commit. Use a clone.
- **No `unclaim`.** A wrong claim is undone by `close --cancel` with a `Verdict:` explaining it, or by
  hand: revert the claim commit, remove the worktree, delete the branch, delete the lease. Record
  which in `tooling-log.md`.
- **Load-sensitive test.** `test_process_start_evidence_is_immune_to_locale_and_timezone` has a ±2 s
  tolerance. It flaked once under heavy CPU load in the source project and passed on re-run.
- **Main moved during close.** The expensive gate runs without the lock. If another task lands in
  between, the real merge can conflict and close aborts cleanly; re-run close.
- **Devcontainers:** everything here is committed in the project, so a rebuild loses nothing except
  `.worktrees/` and leases (gitignored). After a rebuild, `tools/tasks claim` adopts or resumes the
  orphaned tasks.

# reference/tasks — the task-queue kit

Spec: [../../docs/tasks.md](../../docs/tasks.md). This directory mirrors what lands in a target repo.

```
install.sh                 idempotent installer: install.sh [--dry-run] <target-repo>
tools/tasks                launcher (bash) -> python3 -m taskctl.cli, Python >= 3.11, stdlib only
tools/taskctl/             the CLI: claim/close/park/index/resume/status/outcomes/loop-state
tools/taskctl/guard.py     PreToolUse(Bash) hook: refuses hand git mv / rm of task files
template/tasks/            README.md (the contract), gate.cmds, policies.md, tooling-log.md, status dirs
template/.claude/skills/   solve-next-task, solve-next-task-loop, file-tasks   (Claude Code)
template/.agents/skills/   the same three for Codex (+ agents/openai.yaml)
snippets/task-workflow.md  the section appended to the project's AGENTS.md / CLAUDE.md
tests/                     pytest suite for taskctl + guard (88 cases); not installed into targets
```

Run the suite: `PYTHONPATH="$PWD/tools:$PWD/tests" python3 -m pytest -q tests` (needs pytest).

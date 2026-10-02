"""guard: hand moves/deletes of task files are refused; everything else passes (fail open)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from taskctl.guard import violation

GUARD = Path(__file__).resolve().parents[1] / "tools" / "taskctl" / "guard.py"


@pytest.mark.parametrize("cmd", [
    "git mv tasks/todo/0001-a.md tasks/in_progress/",
    "cd /repo && git mv tasks/in_progress/0001-a.md tasks/done/0001-a.md",
    "git -C /repo mv tasks/todo/0001-a.md tasks/cancelled/",
    "mv tasks/todo/0001-a.md tasks/done/",
    "FOO=1 git rm tasks/done/0001-a.md",
    "rm -f /abs/repo/tasks/human_action_required/0003-x.md",
    "echo hi\ngit mv tasks/todo/a.md tasks/done/a.md",
])
def test_refuses_hand_moves(cmd):
    assert violation(cmd)


@pytest.mark.parametrize("cmd", [
    "tools/tasks claim --json",
    "tools/tasks close 42",
    "git add tasks/in_progress/0001-a.md && git commit -m x -- tasks/in_progress/0001-a.md",
    "cat tasks/todo/0001-a.md",
    "rm -rf tasks/.leases/foo.json",
    "rm tasks/todo/.gitkeep",
    "git mv src/a.py src/b.py",
    "grep -r 'git mv tasks/todo' docs/",
    "echo 'mv tasks/todo/x tasks/done/'",
])
def test_allows_everything_else(cmd):
    assert violation(cmd) is None


def _hook(stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GUARD)], input=stdin, text=True, capture_output=True)


def test_hook_exit_codes():
    blocked = _hook(json.dumps({"tool_input": {"command": "git mv tasks/todo/a.md tasks/done/"}}))
    assert blocked.returncode == 2 and "tools/tasks" in blocked.stderr
    assert _hook(json.dumps({"tool_input": {"command": "ls"}})).returncode == 0
    assert _hook("not json").returncode == 0  # fail open
    assert _hook(json.dumps({"tool_input": {"command": "echo 'unterminated"}})).returncode == 0

"""Throwaway git repos for taskctl tests — never the real checkout. Shared by conftest + tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from taskctl.repo import STATUSES, Repo


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


def make_repo(root: Path) -> Repo:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", "."], cwd=root, check=True)
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "tests")
    git(root, "config", "commit.gpgsign", "false")
    for status in STATUSES:
        d = root / "tasks" / status
        d.mkdir(parents=True)
        (d / ".gitkeep").write_text("")
    (root / "README.md").write_text("# throwaway\n")
    (root / ".gitignore").write_text("tasks/.leases/\ntasks/.claim.lock/\n.solve-loop/\n.worktrees/\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return Repo(root)


def base_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TASKS_", "TASK_", "SOLVE_LOOP_"))}
    env.update({"TASKS_PID": str(os.getpid()), "TASKS_SESSION": "test-session", "TASKS_GATE_CMDS": "true",
                "TASKS_LOCK_TIMEOUT": "30"})
    env.update(extra)
    return env


def run_tasks(repo: Repo, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "taskctl.cli", *args], cwd=repo.root, text=True,
                          capture_output=True, env=env or base_env())


def create(repo: Repo, slug: str, **opts: str) -> Path:
    args = ["index", "--create", slug]
    for k, v in opts.items():
        args += [f"--{k.replace('_', '-')}", v]
    proc = run_tasks(repo, *args)
    assert proc.returncode == 0, proc.stderr
    return repo.root / "tasks" / "todo" / next(p.name for p in (repo.root / "tasks" / "todo").glob(f"*-{slug}.md"))


def find(repo: Repo, slug: str) -> Path | None:
    hits = list((repo.root / "tasks").glob(f"*/*-{slug}.md"))
    assert len(hits) <= 1, hits
    return hits[0] if hits else None


def status_of(repo: Repo, slug: str) -> str | None:
    p = find(repo, slug)
    return p.parent.name if p else None

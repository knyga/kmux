"""Fixtures for taskctl tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from _helpers import base_env, make_repo

from taskctl.repo import Repo


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    for k in list(os.environ):
        if k.startswith(("TASKS_", "TASK_", "SOLVE_LOOP_")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TASKS_PID", str(os.getpid()))
    monkeypatch.setenv("TASKS_SESSION", "test-session")
    monkeypatch.setenv("TASKS_LOCK_TIMEOUT", "30")
    return make_repo(tmp_path / "repo")


@pytest.fixture
def other_session():
    """Env for a DIFFERENT live session on this host: its own session id and its own live pid."""
    sleepers: list[subprocess.Popen] = []

    def make(name: str = "intruder", **extra: str) -> dict[str, str]:
        proc = subprocess.Popen(["sleep", "120"])
        sleepers.append(proc)
        return base_env(TASKS_SESSION=name, TASKS_PID=str(proc.pid), **extra)

    yield make
    for proc in sleepers:
        proc.kill()
        proc.wait()

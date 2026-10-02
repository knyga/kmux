"""The claim mutex: stale reclaim, the reclaim race, release safety, and who takes the lock."""

import os
import subprocess
import sys
import time

import pytest
from _helpers import base_env, create, run_tasks

from taskctl.lock import ClaimLock
from taskctl.repo import TaskError


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _plant_lock(repo, pid: int) -> None:
    repo.lock_dir.mkdir(parents=True)
    (repo.lock_dir / "pid").write_text(str(pid))


def test_stale_lock_is_reclaimed(repo):
    _plant_lock(repo, _dead_pid())
    with ClaimLock(repo, timeout=2):
        assert (repo.lock_dir / "pid").read_text() == str(os.getpid())
    assert not repo.lock_dir.exists()


def test_live_lock_blocks_until_timeout(repo):
    _plant_lock(repo, os.getpid())
    with pytest.raises(TaskError, match="could not acquire"):
        ClaimLock(repo, timeout=0.3).acquire()
    assert (repo.lock_dir / "pid").read_text() == str(os.getpid())  # untouched


def test_reclaim_race_gives_a_live_owner_its_lock_back(repo, monkeypatch):
    """Waiter observed a dead owner, got descheduled, and a live owner re-created the lock meanwhile:
    the waiter's rename must not carry the live lock away."""
    _plant_lock(repo, os.getpid())  # the live owner that arrived "in between"
    lock = ClaimLock(repo, timeout=0.3)
    monkeypatch.setattr(lock, "_is_stale", lambda: True)  # the stale observation from before
    monkeypatch.setattr(lock, "_owner_pid", lambda: _dead_pid())
    with pytest.raises(TaskError, match="could not acquire"):
        lock.acquire()
    assert repo.lock_dir.is_dir() and (repo.lock_dir / "pid").read_text() == str(os.getpid())
    assert not list(repo.lock_dir.parent.glob(".claim.lock.stale-*"))


def test_release_never_removes_someone_elses_lock(repo):
    lock = ClaimLock(repo, timeout=1)
    lock.acquire()
    (repo.lock_dir / "pid").write_text("999999")  # somebody else's lock now sits at this path
    lock.release()
    assert repo.lock_dir.is_dir()
    repo.lock_dir.joinpath("pid").unlink()
    repo.lock_dir.rmdir()


def test_heartbeat_and_loop_state_take_the_mutex(repo):
    create(repo, "locked")
    assert run_tasks(repo, "claim").returncode == 0
    sleeper = subprocess.Popen(["sleep", "60"])
    try:
        _plant_lock(repo, sleeper.pid)
        env = base_env(TASKS_LOCK_TIMEOUT="0.3")
        for args in (("claim", "--heartbeat"), ("loop-state", "begin", "locked"),
                     ("loop-state", "record", "locked", "done", "x"), ("loop-state", "reset")):
            proc = run_tasks(repo, *args, env=env)
            assert proc.returncode == 1 and "could not acquire" in proc.stderr, args
    finally:
        sleeper.kill()
        sleeper.wait()
    assert run_tasks(repo, "claim", "--heartbeat").returncode == 0  # stale lock reclaimed once the pid died


def test_reclaim_gives_back_a_fresh_lock_whose_pid_is_not_written_yet(repo, monkeypatch):
    """The mkdir -> pid-write gap: a young dir with no pid file belongs to a live acquirer."""
    repo.lock_dir.mkdir(parents=True)  # no pid file, fresh mtime
    lock = ClaimLock(repo, timeout=0.3)
    monkeypatch.setattr(lock, "_is_stale", lambda: True)
    monkeypatch.setattr(lock, "_owner_pid", lambda: None)
    with pytest.raises(TaskError, match="could not acquire"):
        lock.acquire()
    assert repo.lock_dir.is_dir() and not (repo.lock_dir / "pid").exists()
    assert not list(repo.lock_dir.parent.glob(".claim.lock.stale-*"))
    # an OLD pid-less dir is abandoned and may be reclaimed
    old = time.time() - 60
    os.utime(repo.lock_dir, (old, old))
    monkeypatch.undo()
    with ClaimLock(repo, timeout=1):
        assert (repo.lock_dir / "pid").read_text() == str(os.getpid())

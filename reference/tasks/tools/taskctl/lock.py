"""The one mutex: ``tasks/.claim.lock/`` (mkdir-atomic, owner pid inside).

Stale = owner pid dead on this host. Reclaim is rename-then-delete so two waiters that both observe a
stale lock cannot both "win": only one ``os.rename`` of the stale dir succeeds.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path

from .procs import pid_alive
from .repo import Repo, TaskError

_GRACE_SECONDS = 10.0  # a lock dir without a pid file older than this is considered abandoned


class ClaimLock:
    def __init__(self, repo: Repo, timeout: float | None = None):
        self.path: Path = repo.lock_dir
        self.timeout = float(os.environ.get("TASKS_LOCK_TIMEOUT", "60")) if timeout is None else timeout
        self.held = False

    def _owner_pid(self) -> int | None:
        try:
            return int((self.path / "pid").read_text().strip())
        except (OSError, ValueError):
            return None

    def _is_stale(self) -> bool:
        pid = self._owner_pid()
        if pid is not None:
            return not pid_alive(pid)
        try:
            return time.time() - self.path.stat().st_mtime > _GRACE_SECONDS
        except OSError:
            return False

    def _reclaim(self, observed_dead_pid: int | None) -> None:
        """Take the stale dir away by rename (only one waiter can win the rename), then make sure what we
        carried off is still the dead owner we observed; if a live owner re-created the lock in between,
        put it back untouched and let the acquire loop wait on it."""
        graveyard = self.path.with_name(f".claim.lock.stale-{uuid.uuid4().hex[:8]}")
        try:
            os.rename(self.path, graveyard)
        except OSError:
            return  # somebody else reclaimed it first
        try:
            carried = int((graveyard / "pid").read_text().strip())
        except (OSError, ValueError):
            carried = None
        if carried is None:
            try:
                fresh = time.time() - graveyard.stat().st_mtime < _GRACE_SECONDS
            except OSError:
                fresh = False
        else:
            fresh = False
        # a live owner's lock, or one so young its owner has not written the pid yet: give it back
        if fresh or (carried is not None and carried != observed_dead_pid and pid_alive(carried)):
            for _ in range(200):
                try:
                    os.rename(graveyard, self.path)
                    return
                except OSError:
                    time.sleep(0.01)
            shutil.rmtree(graveyard, ignore_errors=True)
            return
        shutil.rmtree(graveyard, ignore_errors=True)

    def acquire(self) -> None:
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                os.mkdir(self.path)
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise TaskError(
                        f"could not acquire {self.path} within {self.timeout:.0f}s "
                        f"(held by pid {self._owner_pid()})"
                    ) from None
                owner = self._owner_pid()
                if self._is_stale():
                    self._reclaim(owner)
                    continue
                time.sleep(0.05)
                continue
            (self.path / "pid").write_text(str(os.getpid()))
            self.held = True
            return

    def release(self) -> None:
        """Remove the lock only if it is still ours (pid file names this process)."""
        if self.held:
            self.held = False
            if self._owner_pid() == os.getpid():
                shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> ClaimLock:
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()

"""Lease files ``tasks/.leases/<slug>.json`` (gitignored)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from .procs import hostname, pid_alive, proc_start_matches
from .repo import Repo


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def lease_minutes() -> float:
    try:
        return float(os.environ.get("TASK_LEASE_MINUTES", "60"))
    except ValueError:
        return 60.0


@dataclass
class Lease:
    slug: str
    session: str
    pid: int
    host: str
    branch: str
    worktree: str
    heartbeatAt: str  # the on-disk key
    pidStart: str = ""  # epoch seconds the pid started (from ps etimes); guards against pid reuse

    @property
    def heartbeat(self) -> datetime | None:
        return parse_iso(self.heartbeatAt)

    def same_host(self) -> bool:
        return self.host == hostname()

    def is_live(self, now: datetime | None = None) -> bool:
        """Same host: pid alive AND started when we recorded (evidence). Other host: heartbeat
        younger than TASK_LEASE_MINUTES."""
        if self.same_host():
            if not pid_alive(self.pid):
                return False
            return proc_start_matches(self.pid, self.pidStart)
        hb = self.heartbeat
        if hb is None:
            return False
        return (now or now_utc()) - hb < timedelta(minutes=lease_minutes())

    def age(self, now: datetime | None = None) -> timedelta | None:
        hb = self.heartbeat
        return None if hb is None else (now or now_utc()) - hb

    def verdict(self) -> str:
        if self.is_live():
            return "live"
        return "dead" if self.same_host() else "expired"


def path_for(repo: Repo, slug: str):
    return repo.leases_dir / f"{slug}.json"


def load(repo: Repo, slug: str) -> Lease | None:
    p = path_for(repo, slug)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return Lease(slug=slug, session=str(data.get("session", "")), pid=int(data.get("pid", 0) or 0),
                     host=str(data.get("host", "")), branch=str(data.get("branch", "")),
                     worktree=str(data.get("worktree", "")), heartbeatAt=str(data.get("heartbeatAt", "")),
                     pidStart=str(data.get("pidStart", "")))
    except (OSError, ValueError, TypeError):
        return None


def load_all(repo: Repo) -> dict[str, Lease]:
    out: dict[str, Lease] = {}
    if not repo.leases_dir.exists():
        return out
    for p in sorted(repo.leases_dir.glob("*.json")):
        lease = load(repo, p.stem)
        if lease is not None:
            out[p.stem] = lease
    return out


def write(repo: Repo, lease: Lease) -> None:
    repo.leases_dir.mkdir(parents=True, exist_ok=True)
    data = asdict(lease)
    data.pop("slug")
    tmp = path_for(repo, lease.slug).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path_for(repo, lease.slug))


def drop(repo: Repo, slug: str) -> None:
    try:
        path_for(repo, slug).unlink()
    except FileNotFoundError:
        pass

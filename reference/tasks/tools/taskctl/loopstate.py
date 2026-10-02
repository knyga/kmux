"""Solve-loop bookkeeping in ``.solve-loop/state.json`` (gitignored). Writes run under the tracker mutex."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime

from .lock import ClaimLock
from .repo import EXIT_REFUSED, Repo, TaskError

STATUSES = ("done", "parked", "cancelled", "stalled")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _empty() -> dict:
    return {"session": "", "attempts": {}, "totals": dict.fromkeys(STATUSES, 0), "consecutive_stalls": 0,
            "history": []}


def load(repo: Repo) -> dict:
    p = repo.loop_state_path
    if not p.exists():
        return _empty()
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return _empty()
    base = _empty()
    base.update({k: v for k, v in data.items() if k in base})
    for k in STATUSES:
        base["totals"].setdefault(k, 0)
    return base


def save(repo: Repo, state: dict) -> None:
    p = repo.loop_state_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n")


def session(repo: Repo) -> str:
    """The run's TASKS_SESSION id, persisted on disk so a coordinator whose context was lost (a later
    `/loop` turn, a reconnected terminal) keeps claiming as the SAME identity; a new id would make its
    own stalled task look foreign and wedge it. `reset` clears it (a fresh run gets a fresh id)."""
    with ClaimLock(repo):
        state = load(repo)
        if not state.get("session"):
            state["session"] = f"loop-{datetime.now().strftime('%Y%m%d-%H%M')}-{secrets.token_hex(2)}"
            save(repo, state)
    return state["session"]


def begin(repo: Repo, slug: str) -> dict:
    with ClaimLock(repo):
        state = load(repo)
        attempts = state["attempts"].get(slug, 0) + 1
        state["attempts"][slug] = attempts
        save(repo, state)
    return {"slug": slug, "attempts": attempts,
            "shouldPark": attempts > _env_int("SOLVE_LOOP_MAX_ATTEMPTS", 2)}


def record(repo: Repo, slug: str, status: str, note: str) -> dict:
    if status not in STATUSES:
        raise TaskError(f"status must be one of {', '.join(STATUSES)}", EXIT_REFUSED)
    with ClaimLock(repo):
        state = load(repo)
        state["totals"][status] = state["totals"].get(status, 0) + 1
        state["consecutive_stalls"] = state["consecutive_stalls"] + 1 if status == "stalled" else 0
        state["history"].append({"at": datetime.now().astimezone().isoformat(timespec="seconds"),
                                 "slug": slug, "status": status, "note": note})
        save(repo, state)
    totals = state["totals"]
    max_stalls = _env_int("SOLVE_LOOP_MAX_STALLS", 3)
    max_tasks = _env_int("SOLVE_LOOP_MAX_TASKS", 0)
    settled = totals["done"] + totals["parked"] + totals["cancelled"]
    decision, reason = "continue", "budget remaining"
    if state["consecutive_stalls"] >= max_stalls:
        decision, reason = "stop", f"{state['consecutive_stalls']} consecutive stalls (max {max_stalls})"
    elif max_tasks and settled >= max_tasks:
        decision, reason = "stop", f"{settled} tasks settled (max {max_tasks})"
    return {"decision": decision, "reason": reason, "totals": {k: totals[k] for k in STATUSES}}


def report(repo: Repo) -> dict:
    state = load(repo)
    return {"session": state.get("session", ""), "totals": state["totals"],
            "consecutive_stalls": state["consecutive_stalls"], "attempts": state["attempts"],
            "history": state["history"]}


def reset(repo: Repo) -> None:
    with ClaimLock(repo):
        try:
            repo.loop_state_path.unlink()
        except FileNotFoundError:
            pass

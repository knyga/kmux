"""The claim command: race under the mutex, pool order, lease liveness, refusals."""

import json
import os
import pathlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from _helpers import base_env, create, git, run_tasks, status_of

from taskctl import lease as leases


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_claim_race_one_task_exactly_one_winner(repo, other_session):
    create(repo, "only-one")
    envs = [other_session("racer-a"), other_session("racer-b")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        procs = list(pool.map(lambda env: run_tasks(repo, "claim", "--json", env=env), envs))
    codes = sorted(p.returncode for p in procs)
    assert codes == [0, 3], [(p.returncode, p.stdout, p.stderr) for p in procs]
    winner = next(p for p in procs if p.returncode == 0)
    payload = json.loads(winner.stdout)
    assert payload["slug"] == "only-one" and payload["mode"] == "new"
    assert status_of(repo, "only-one") == "in_progress"
    assert (repo.root / ".worktrees" / "only-one").is_dir()
    assert git(repo.root, "rev-parse", "--verify", "refs/heads/only-one")
    assert leases.load(repo, "only-one").is_live()
    assert not (repo.root / "tasks" / ".claim.lock").exists()
    assert git(repo.root, "status", "--short") == ""


def test_nothing_available_exits_3(repo):
    proc = run_tasks(repo, "claim")
    assert proc.returncode == 3 and "nothing available" in proc.stdout


def test_ranking_within_todo_pool(repo):
    create(repo, "low", priority="p3")
    create(repo, "chore-first", priority="p1", type="chore")
    create(repo, "bug-later", priority="p1", type="bug")
    proc = run_tasks(repo, "claim", "--json")
    assert json.loads(proc.stdout)["slug"] == "bug-later"


def test_resume_pool_wins_when_session_pid_is_dead(repo):
    create(repo, "dropped", priority="p3")
    create(repo, "shiny", priority="p0")
    first = run_tasks(repo, "claim", "--slug", "dropped", "--json", env=base_env(TASKS_PID=str(_dead_pid())))
    assert first.returncode == 0, first.stderr
    second = run_tasks(repo, "claim", "--json")
    payload = json.loads(second.stdout)
    assert (payload["slug"], payload["mode"]) == ("dropped", "resume")
    assert leases.load(repo, "dropped").pid == os.getpid()
    progress = (repo.root / "tasks" / "in_progress" / "0001-dropped.md").read_text()
    assert "(mode=slug)" in progress and "(mode=resume)" in progress


def test_adopt_pool_takes_stale_unleased_work_from_other_host(repo, other_session):
    create(repo, "abandoned", priority="p3")
    create(repo, "fresh", priority="p0")
    other = base_env(TASKS_HOST="other-host", TASKS_SESSION="far-away", TASKS_PID=str(_dead_pid()))
    assert run_tasks(repo, "claim", "--slug", "abandoned", "--json", env=other).returncode == 0
    # lease from another host, heartbeat is recent -> live -> not adoptable, fresh p0 wins
    live = run_tasks(repo, "claim", "--json", env=other_session("bystander", TASKS_STALE_HOURS="0"))
    assert json.loads(live.stdout)["slug"] == "fresh"
    # expire the other host's lease -> stale + unleased -> adopt beats todo
    create(repo, "another", priority="p0")
    adopt = run_tasks(repo, "claim", "--json", env=base_env(TASKS_STALE_HOURS="0", TASK_LEASE_MINUTES="0",
                                                            TASKS_SESSION="second"))
    payload = json.loads(adopt.stdout)
    assert (payload["slug"], payload["mode"]) == ("abandoned", "adopt")


def test_slug_claim_refused_when_live_session_holds_it(repo, other_session):
    create(repo, "held")
    assert run_tasks(repo, "claim", "--slug", "held").returncode == 0
    other = run_tasks(repo, "claim", "--slug", "held", env=other_session("intruder"))
    assert other.returncode == 4 and "held by live session test-session" in other.stderr
    same = run_tasks(repo, "claim", "--slug", "held", "--json")  # same session may re-claim
    assert same.returncode == 0 and json.loads(same.stdout)["mode"] == "slug"
    unknown = run_tasks(repo, "claim", "--slug", "nope")
    assert unknown.returncode == 4 and "unknown task" in unknown.stderr


def test_heartbeat_and_status(repo):
    create(repo, "beat")
    assert run_tasks(repo, "claim").returncode == 0
    before = leases.load(repo, "beat").heartbeatAt
    hb = run_tasks(repo, "claim", "--heartbeat")
    assert hb.returncode == 0 and "heartbeat beat" in hb.stdout
    assert leases.load(repo, "beat").heartbeatAt >= before
    st = run_tasks(repo, "status")
    assert "beat" in st.stdout and "live" in st.stdout
    assert "(no adoptable tasks)" in run_tasks(repo, "status", "--stale").stdout
    create(repo, "orphan")
    assert run_tasks(repo, "claim", "--slug", "orphan", env=base_env(TASKS_PID=str(_dead_pid()))).returncode == 0
    dead = run_tasks(repo, "status", "--stale")
    assert "orphan" in dead.stdout and "adoptable" in dead.stdout and "beat" not in dead.stdout


def test_park_and_resume_briefing(repo):
    create(repo, "parkme")
    assert run_tasks(repo, "claim").returncode == 0
    parked = run_tasks(repo, "park", "parkme", "--reason", "need API key from owner")
    assert parked.returncode == 0
    assert status_of(repo, "parkme") == "human_action_required"
    assert leases.load(repo, "parkme") is None
    text = (repo.root / "tasks" / "human_action_required" / "0001-parkme.md").read_text()
    assert "parked: need API key from owner" in text
    assert run_tasks(repo, "claim").returncode == 3  # parked work is not re-picked while fresh
    brief = run_tasks(repo, "resume", "parkme")
    assert brief.returncode == 0
    assert "## Progress" in brief.stdout and "parked:" in brief.stdout and "Unchecked items" in brief.stdout


def test_crash_between_rename_and_commit_is_healed_by_next_commit(repo):
    """A claim killed after the rename but before its commit must not leave HEAD with the file at two
    paths or the index dirty (that wedged every later close)."""
    src = create(repo, "torn")
    dst = repo.root / "tasks" / "in_progress" / src.name
    src.rename(dst)  # simulate: rename happened, process died before commit
    assert run_tasks(repo, "claim", "--slug", "torn").returncode == 0
    assert git(repo.root, "status", "--short") == ""
    tracked = git(repo.root, "ls-tree", "-r", "--name-only", "HEAD", "tasks/").splitlines()
    assert [t for t in tracked if t.endswith("-torn.md")] == ["tasks/in_progress/0001-torn.md"]


def test_stalled_task_reenters_as_resume_for_the_same_session(repo):
    """Loop stall recovery: the file stays in in_progress/ with a LIVE lease held by this session;
    the next claim must hand back the same slug (mode resume) instead of moving on."""
    create(repo, "stalled", priority="p0")
    create(repo, "other", priority="p1")
    first = json.loads(run_tasks(repo, "claim", "--json").stdout)
    assert first["slug"] == "stalled"
    again = json.loads(run_tasks(repo, "claim", "--json").stdout)  # same TASKS_SESSION
    assert (again["slug"], again["mode"]) == ("stalled", "resume")
    # a coordinator without TASKS_SESSION exported still gets it back: same host, same session pid
    fresh_session = base_env()
    del fresh_session["TASKS_SESSION"]
    third = json.loads(run_tasks(repo, "claim", "--json", env=fresh_session).stdout)
    assert (third["slug"], third["mode"]) == ("stalled", "resume")
    assert status_of(repo, "other") == "todo"


def test_leaseless_in_progress_task_claimed_on_this_host_is_resumed(repo):
    """Also exercises the host= claim line with a session id containing spaces."""
    """Claim interrupted after the tracker commit but before the lease write: no lease, not stale,
    but the Progress line names this host -> RESUME, not stranded for 24 h."""
    create(repo, "torn-lease", priority="p3")
    create(repo, "tempting", priority="p0")
    assert run_tasks(repo, "claim", "--slug", "torn-lease", env=base_env(TASKS_SESSION="loop run 1")).returncode == 0
    (repo.root / "tasks" / ".leases" / "torn-lease.json").unlink()
    payload = json.loads(run_tasks(repo, "claim", "--json", env=base_env(TASKS_SESSION="new-session")).stdout)
    assert (payload["slug"], payload["mode"]) == ("torn-lease", "resume")
    assert leases.load(repo, "torn-lease") is not None


def test_resume_claim_reuses_branch_and_worktree(repo):
    create(repo, "reuse")
    first = json.loads(run_tasks(repo, "claim", "--json").stdout)
    wt = repo.root / ".worktrees" / "reuse"
    (wt / "work.txt").write_text("kept\n")
    subprocess.run(["git", "add", "work.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-qm", "wip on branch"], cwd=wt, check=True)
    (wt / "uncommitted.txt").write_text("also kept\n")
    again = json.loads(run_tasks(repo, "claim", "--json").stdout)
    assert again["mode"] == "resume" and again["worktree"] == first["worktree"] and again["branch"] == "reuse"
    assert git(repo.root, "log", "--oneline", "main..reuse").endswith("wip on branch")
    assert (wt / "uncommitted.txt").read_text() == "also kept\n"
    assert len(git(repo.root, "worktree", "list").splitlines()) == 2  # main + one task worktree


def test_recycled_pid_does_not_keep_a_lease_alive(repo):
    """Liveness = pid alive AND the same process start time; a lease whose pid was recycled is dead."""
    from taskctl.procs import proc_start

    assert proc_start(os.getpid()).isdigit()
    create(repo, "recycled", priority="p3")
    create(repo, "shiny", priority="p0")
    assert run_tasks(repo, "claim", "--slug", "recycled", env=base_env(TASKS_SESSION="gone")).returncode == 0
    lease = leases.load(repo, "recycled")
    assert abs(int(lease.pidStart) - int(proc_start(os.getpid()))) <= 2 and lease.is_live()
    lease.pidStart = str(int(lease.pidStart) - 3600)  # same (live) pid, an incarnation from an hour ago
    leases.write(repo, lease)
    assert not leases.load(repo, "recycled").is_live()
    assert "dead" in run_tasks(repo, "status").stdout
    payload = json.loads(run_tasks(repo, "claim", "--json").stdout)
    assert (payload["slug"], payload["mode"]) == ("recycled", "resume")
    assert abs(int(leases.load(repo, "recycled").pidStart) - int(proc_start(os.getpid()))) <= 2


def test_unpreparable_worktree_is_skipped_not_a_wedge(repo):
    """A stray unregistered .worktrees/<slug> must not block the queue: the claim prints the skip,
    moves nothing for that task, and claims the next candidate."""
    create(repo, "stray", priority="p0")
    create(repo, "beta", priority="p1")
    (repo.root / ".worktrees" / "stray").mkdir(parents=True)
    (repo.root / ".worktrees" / "stray" / "junk").write_text("x\n")
    proc = run_tasks(repo, "claim", "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["slug"] == "beta"
    assert "skipped (worktree): tasks/todo/0001-stray.md" in proc.stderr
    assert status_of(repo, "stray") == "todo" and leases.load(repo, "stray") is None
    assert not git(repo.root, "log", "--oneline", "--all", "--", "tasks/in_progress/0001-stray.md")
    explicit = run_tasks(repo, "claim", "--slug", "stray")
    assert explicit.returncode == 4 and "not a registered worktree" in explicit.stderr
    assert status_of(repo, "stray") == "todo"  # refused before the move: nothing committed


def test_named_sessions_sharing_a_pid_do_not_take_each_others_tasks(repo):
    """Two subagents under one coordinator share the long-lived pid but name distinct sessions:
    subB must not resume subA's task, and --slug / heartbeat must refuse it."""
    create(repo, "alpha", priority="p0")
    create(repo, "beta", priority="p1")
    a = json.loads(run_tasks(repo, "claim", "--json", env=base_env(TASKS_SESSION="subA")).stdout)
    assert a["slug"] == "alpha"
    b = json.loads(run_tasks(repo, "claim", "--json", env=base_env(TASKS_SESSION="subB")).stdout)
    assert (b["slug"], b["mode"]) == ("beta", "new")
    assert leases.load(repo, "alpha").session == "subA"
    assert run_tasks(repo, "claim", "--slug", "alpha", env=base_env(TASKS_SESSION="subB")).returncode == 4
    anon = base_env()
    del anon["TASKS_SESSION"]  # anonymous caller on the same process: pid fallback still applies
    c = json.loads(run_tasks(repo, "claim", "--json", env=anon).stdout)
    assert c["mode"] == "resume" and c["slug"] in ("alpha", "beta")


def test_process_start_evidence_is_immune_to_locale_and_timezone(repo, monkeypatch):
    """The old `ps -o lstart=` string changed with TZ/LC_*; the numeric start must not."""
    from taskctl.procs import proc_start, proc_start_matches

    base = proc_start(os.getpid())
    assert base.isdigit()
    for tz, loc in (("Asia/Tokyo", "ja_JP.UTF-8"), ("UTC", "de_DE.UTF-8"), ("America/Los_Angeles", "fr_FR.UTF-8")):
        monkeypatch.setenv("TZ", tz)
        monkeypatch.setenv("LC_ALL", loc)
        monkeypatch.setenv("LC_TIME", loc)
        assert proc_start_matches(os.getpid(), base), (tz, loc, proc_start(os.getpid()), base)


def test_process_start_matches_tolerance_boundary(monkeypatch):
    from taskctl import procs

    # Independent ps readings can jitter by a second. Use one fixed reading for
    # exact tolerance boundaries; keep real process reads in the locale test.
    monkeypatch.setattr(procs, "proc_start", lambda pid: "1000")
    for offset in (-2, -1, 0, 1, 2):
        assert procs.proc_start_matches(os.getpid(), str(1000 + offset))
    for offset in (-3, 3):
        assert not procs.proc_start_matches(os.getpid(), str(1000 + offset))


def test_process_start_matches_with_jitter(monkeypatch):
    from taskctl import procs

    for jitter in (-1, 1):
        readings = iter(("1000", str(1000 + jitter)))
        monkeypatch.setattr(procs, "proc_start", lambda pid, readings=readings: next(readings))
        base = procs.proc_start(os.getpid())
        assert procs.proc_start_matches(os.getpid(), base)


def test_process_start_matches_unknown_evidence(monkeypatch):
    from taskctl.procs import proc_start_matches

    monkeypatch.setattr("taskctl.procs.proc_start", lambda pid: "1000")
    assert proc_start_matches(os.getpid(), "Mon Sep  7 20:57:32 2026")  # legacy lstart record: unknown -> fail open
    assert proc_start_matches(os.getpid(), "")
    monkeypatch.setattr("taskctl.procs.proc_start", lambda pid: "")
    assert proc_start_matches(os.getpid(), "1000")


def test_branch_checked_out_in_main_checkout_refuses_the_claim(repo):
    create(repo, "held-here", priority="p0")
    create(repo, "spare", priority="p1")
    subprocess.run(["git", "checkout", "-qb", "held-here"], cwd=repo.root, check=True)
    explicit = run_tasks(repo, "claim", "--slug", "held-here", "--json")
    assert explicit.returncode == 4 and "checked out in the main checkout" in explicit.stderr
    assert status_of(repo, "held-here") == "todo"
    picked = run_tasks(repo, "claim", "--json")
    assert picked.returncode == 0 and json.loads(picked.stdout)["slug"] == "spare"
    assert "skipped (worktree): tasks/todo/0001-held-here.md" in picked.stderr
    assert json.loads(picked.stdout)["worktree"] != str(repo.root)


def test_fresh_claim_worktree_contains_the_in_progress_file(repo):
    create(repo, "ffwd")
    payload = json.loads(run_tasks(repo, "claim", "--json").stdout)
    wt = repo.root / payload["worktree"] if not payload["worktree"].startswith("/") else pathlib.Path(payload["worktree"])
    assert (wt / payload["file"]).exists() and "claimed by test-session" in (wt / payload["file"]).read_text()
    assert not (wt / "tasks" / "todo" / "0001-ffwd.md").exists()
    assert git(repo.root, "rev-list", "--count", "ffwd..main") == "0"
    assert git(repo.root, "rev-list", "--count", "main..ffwd") == "0"
    # a branch with its own commits is left alone on re-claim
    (wt / "own.txt").write_text("x\n")
    subprocess.run(["git", "add", "own.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-qm", "own"], cwd=wt, check=True)
    assert run_tasks(repo, "claim", "--json").returncode == 0  # resume: another claim commit on main
    assert git(repo.root, "rev-list", "--count", "ffwd..main") == "1"
    assert git(repo.root, "log", "-1", "--format=%s", "ffwd") == "own"


def test_failing_claim_commit_is_rolled_back_and_skipped(repo):
    """A pre-commit hook rejects commits touching alpha: the claim restores alpha untouched, leaves the
    index clean, prints the skip and claims beta instead."""
    create(repo, "alpha", priority="p0")
    create(repo, "beta", priority="p1")
    before = (repo.root / "tasks" / "todo" / "0001-alpha.md").read_text()
    hook = repo.root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ngit diff --cached --name-only | grep -q 0001-alpha && exit 1\nexit 0\n")
    hook.chmod(0o755)
    proc = run_tasks(repo, "claim", "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["slug"] == "beta"
    assert "skipped (commit): tasks/todo/0001-alpha.md" in proc.stderr
    assert status_of(repo, "alpha") == "todo" and (repo.root / "tasks" / "todo" / "0001-alpha.md").read_text() == before
    assert git(repo.root, "status", "--short") == "" and git(repo.root, "diff", "--cached", "--name-only") == ""
    assert leases.load(repo, "alpha") is None
    explicit = run_tasks(repo, "claim", "--slug", "alpha")
    assert explicit.returncode != 0 and status_of(repo, "alpha") == "todo" and git(repo.root, "status", "--short") == ""


def test_heartbeat_and_resume_respect_session_identity(repo):
    create(repo, "alpha", priority="p0")
    assert json.loads(run_tasks(repo, "claim", "--json", env=base_env(TASKS_SESSION="subA")).stdout)["slug"] == "alpha"
    before = leases.load(repo, "alpha")
    hb = run_tasks(repo, "claim", "--heartbeat", env=base_env(TASKS_SESSION="subB"))  # shared pid, other id
    assert hb.returncode == 4 and "no lease for this session" in hb.stderr
    after = leases.load(repo, "alpha")
    assert (after.session, after.heartbeatAt) == ("subA", before.heartbeatAt)
    res = run_tasks(repo, "resume", env=base_env(TASKS_SESSION="subB"))
    assert res.returncode == 4 and "nothing to resume" in res.stderr and "alpha" not in res.stdout
    assert run_tasks(repo, "claim", "--heartbeat", env=base_env(TASKS_SESSION="subA")).returncode == 0
    assert "resume 0001-alpha" in run_tasks(repo, "resume", env=base_env(TASKS_SESSION="subA")).stdout


def test_park_refuses_a_task_held_by_another_live_session(repo, other_session):
    create(repo, "theirs")
    assert run_tasks(repo, "claim", "--slug", "theirs").returncode == 0
    proc = run_tasks(repo, "park", "theirs", "--reason", "steal", env=other_session("stranger"))
    assert proc.returncode == 4 and "held by live session test-session" in proc.stderr
    assert status_of(repo, "theirs") == "in_progress" and leases.load(repo, "theirs") is not None
    shared_pid_other_id = run_tasks(repo, "park", "theirs", "--reason", "steal", env=base_env(TASKS_SESSION="subB"))
    assert shared_pid_other_id.returncode == 4
    assert run_tasks(repo, "park", "theirs", "--reason", "owner decision needed").returncode == 0

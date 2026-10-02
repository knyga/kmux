"""close: refusals move nothing; the happy path gates, lands with --no-ff, moves, retires."""

import subprocess

from _helpers import base_env, create, git, run_tasks, status_of

from taskctl import lease as leases

OUTCOME_OK = "Measured: it works.\nVerdict: shipped."


def _claimed(repo, slug: str, *, items_done=True, verdict=True, followups: str | None = None):
    create(repo, slug)
    assert run_tasks(repo, "claim", "--slug", slug).returncode == 0
    p = repo.root / "tasks" / "in_progress" / f"0001-{slug}.md"
    s = p.read_text()
    if items_done:
        s = s.replace("- [ ] 1. ...", "- [x] 1. done")
    if verdict:
        s = s.replace("<!-- filled DURING the work, the same turn a fact is measured. Verdict mandatory before close. -->",
                      OUTCOME_OK)
    if followups is not None:
        s = s.replace("## Progress", f"## Followups\n{followups}\n\n## Progress")
    p.write_text(s)
    subprocess.run(["git", "commit", "-qm", "edit", "--", str(p)], cwd=repo.root, check=False)
    return p


def _assert_nothing_moved(repo, slug: str):
    assert status_of(repo, slug) == "in_progress"
    assert leases.load(repo, slug) is not None
    assert (repo.root / ".worktrees" / slug).is_dir()
    assert git(repo.root, "rev-parse", "--verify", f"refs/heads/{slug}")
    assert git(repo.root, "status", "--short") == ""
    assert not (repo.root / "tasks" / ".claim.lock").exists()


def test_refuses_unchecked_items_and_missing_verdict_at_once(repo):
    _claimed(repo, "raw", items_done=False, verdict=False)
    proc = run_tasks(repo, "close", "raw")
    assert proc.returncode == 2
    assert "unchecked item: - [ ] 1. ..." in proc.stderr
    assert "no line matching 'Verdict:'" in proc.stderr
    assert "nothing moved" in proc.stderr
    _assert_nothing_moved(repo, "raw")
    cancel = run_tasks(repo, "close", "raw", "--cancel")
    assert cancel.returncode == 2 and "Verdict" in cancel.stderr  # verdict is mandatory for --cancel too
    assert "unchecked item" not in cancel.stderr  # …but items/followups gate done only
    _assert_nothing_moved(repo, "raw")


def test_refuses_unresolved_followups(repo):
    _claimed(repo, "fu", followups="- [x] handled\n- promoted: tasks/*/0002-next.md\n- wontfix: too small\n- left dangling")
    proc = run_tasks(repo, "close", "fu")
    assert proc.returncode == 2 and "unresolved followup: - left dangling" in proc.stderr
    _assert_nothing_moved(repo, "fu")


def test_refuses_when_expensive_gate_fails(repo):
    _claimed(repo, "gated")
    wt = repo.root / ".worktrees" / "gated"
    (wt / "new.txt").write_text("x\n")
    subprocess.run(["git", "add", "new.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-qm", "work"], cwd=wt, check=True)
    proc = run_tasks(repo, "close", "gated", env=base_env(TASKS_GATE_CMDS="true ;; false"))
    assert proc.returncode == 2 and "gate failed (1): false" in proc.stderr
    _assert_nothing_moved(repo, "gated")
    assert not list((repo.root / ".worktrees").glob("_gate-*"))  # throwaway worktree cleaned up
    assert git(repo.root, "rev-parse", "main") == git(repo.root, "rev-parse", "HEAD")


def test_refuses_conflicting_merge_and_aborts(repo):
    _claimed(repo, "conflict")
    wt = repo.root / ".worktrees" / "conflict"
    (wt / "README.md").write_text("branch version\n")
    subprocess.run(["git", "commit", "-qam", "branch edit"], cwd=wt, check=True)
    (repo.root / "README.md").write_text("main version\n")
    subprocess.run(["git", "commit", "-qam", "main edit"], cwd=repo.root, check=True)
    proc = run_tasks(repo, "close", "conflict")
    assert proc.returncode == 2 and "does not complete cleanly" in proc.stderr
    _assert_nothing_moved(repo, "conflict")
    assert (repo.root / "README.md").read_text() == "main version\n"


def test_dry_run_then_close_lands_and_retires(repo):
    _claimed(repo, "ship")
    wt = repo.root / ".worktrees" / "ship"
    (wt / "feature.txt").write_text("done\n")
    subprocess.run(["git", "add", "feature.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-qm", "feat: feature"], cwd=wt, check=True)
    dry = run_tasks(repo, "close", "ship", "--dry-run")
    assert dry.returncode == 0 and dry.stdout.startswith("would:") and "merge --no-ff ship" in dry.stdout
    _assert_nothing_moved(repo, "ship")
    real = run_tasks(repo, "close", "ship")
    assert real.returncode == 0, real.stderr
    assert status_of(repo, "ship") == "done"
    assert (repo.root / "feature.txt").read_text() == "done\n"
    assert git(repo.root, "log", "-1", "--format=%s", "HEAD~1").startswith("Merge branch 'ship'")
    assert len(git(repo.root, "rev-list", "--parents", "-1", "HEAD~1").split()) == 3  # a real merge commit
    assert leases.load(repo, "ship") is None
    assert not wt.exists()
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/heads/ship"], cwd=repo.root).returncode != 0
    assert "closed: merged as" in (repo.root / "tasks" / "done" / "0001-ship.md").read_text()
    assert git(repo.root, "status", "--short") == ""
    assert run_tasks(repo, "close", "ship").returncode == 4  # already done
    assert "it works" in run_tasks(repo, "outcomes", "WORKS").stdout


def test_cancel_moves_to_cancelled_without_merging(repo):
    _claimed(repo, "drop", items_done=False)
    wt = repo.root / ".worktrees" / "drop"
    (wt / "junk.txt").write_text("x\n")
    subprocess.run(["git", "add", "junk.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-qm", "junk"], cwd=wt, check=True)
    # cancel needs the Verdict only: unchecked items are fine, and the expensive gate never runs
    proc = run_tasks(repo, "close", "drop", "--cancel", env=base_env(TASKS_GATE_CMDS="false"))
    assert proc.returncode == 0, proc.stderr
    assert status_of(repo, "drop") == "cancelled"
    assert not (repo.root / "junk.txt").exists()
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/heads/drop"], cwd=repo.root).returncode != 0
    assert git(repo.root, "status", "--short") == ""


def test_refuses_when_index_is_dirty_and_names_the_paths(repo):
    _claimed(repo, "staged")
    wt = repo.root / ".worktrees" / "staged"
    (wt / "f.txt").write_text("x\n")
    subprocess.run(["git", "add", "f.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-qm", "work"], cwd=wt, check=True)  # something to land
    (repo.root / "unrelated.txt").write_text("staged but uncommitted\n")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=repo.root, check=True)
    proc = run_tasks(repo, "close", "staged")
    assert proc.returncode == 2 and "git restore --staged -- unrelated.txt" in proc.stderr
    assert status_of(repo, "staged") == "in_progress"
    assert git(repo.root, "diff", "--cached", "--name-only") == "unrelated.txt"  # untouched
    # nothing lands under --no-merge, so the staged file is not its problem (and stays staged, untouched)
    assert run_tasks(repo, "close", "staged", "--no-merge").returncode == 0
    assert git(repo.root, "diff", "--cached", "--name-only") == "unrelated.txt"


def test_cancel_ignores_a_dirty_index(repo):
    _claimed(repo, "cancel-staged", items_done=False)
    (repo.root / "unrelated.txt").write_text("staged\n")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=repo.root, check=True)
    assert run_tasks(repo, "close", "cancel-staged", "--cancel").returncode == 0
    assert status_of(repo, "cancel-staged") == "cancelled"


def test_wrong_branch_is_refused_before_the_expensive_gate(repo):
    _claimed(repo, "offmain")
    wt = repo.root / ".worktrees" / "offmain"
    (wt / "f.txt").write_text("x\n")
    subprocess.run(["git", "add", "f.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-qm", "work"], cwd=wt, check=True)
    subprocess.run(["git", "checkout", "-qb", "elsewhere"], cwd=repo.root, check=True)
    marker = repo.root / ".gate-ran"
    proc = run_tasks(repo, "close", "offmain", env=base_env(TASKS_GATE_CMDS=f"touch {marker}"))
    assert proc.returncode == 2 and "main checkout is on 'elsewhere', not 'main'" in proc.stderr
    assert not marker.exists()  # refused in phase 1, expensive gate never ran
    _assert_nothing_moved(repo, "offmain")
    # --no-merge does not need main
    assert run_tasks(repo, "close", "offmain", "--no-merge", env=base_env(TASKS_GATE_CMDS=f"touch {marker}")).returncode == 0
    assert status_of(repo, "offmain") == "done"


def test_dirty_worktree_is_refused_unless_forced(repo):
    _claimed(repo, "dirty")
    wt = repo.root / ".worktrees" / "dirty"
    (wt / "wip.txt").write_text("not committed\n")
    proc = run_tasks(repo, "close", "dirty")
    assert proc.returncode == 2 and "has uncommitted changes" in proc.stderr and "?? wip.txt" in proc.stderr
    _assert_nothing_moved(repo, "dirty")
    assert (wt / "wip.txt").exists()
    assert run_tasks(repo, "close", "dirty", "--force-worktree").returncode == 0
    assert status_of(repo, "dirty") == "done" and not wt.exists()


def test_landing_refusal_after_a_passing_gate_aborts_and_moves_nothing(repo):
    """Gate passes (the throwaway worktree is clean) but the --no-ff merge in the main checkout cannot
    complete: an UNSTAGED edit to a file the branch also changes. Nothing moves, no MERGE_HEAD."""
    _claimed(repo, "landfail")
    wt = repo.root / ".worktrees" / "landfail"
    (wt / "README.md").write_text("branch version\n")
    subprocess.run(["git", "commit", "-qam", "branch edit"], cwd=wt, check=True)
    (repo.root / "README.md").write_text("uncommitted local edit\n")
    proc = run_tasks(repo, "close", "landfail")
    assert proc.returncode == 2 and "git merge --no-ff landfail did not complete cleanly" in proc.stderr
    assert not (repo.root / ".git" / "MERGE_HEAD").exists()
    assert (repo.root / "README.md").read_text() == "uncommitted local edit\n"
    assert git(repo.root, "status", "--short").split() == ["M", "README.md"]
    assert status_of(repo, "landfail") == "in_progress"
    assert leases.load(repo, "landfail") is not None and wt.is_dir()
    assert git(repo.root, "rev-parse", "main") == git(repo.root, "rev-parse", "HEAD")


def test_no_merge_closes_without_landing_and_keeps_the_branch(repo):
    _claimed(repo, "nomerge")
    wt = repo.root / ".worktrees" / "nomerge"
    (wt / "kept.txt").write_text("on branch only\n")
    subprocess.run(["git", "add", "kept.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-qm", "branch work"], cwd=wt, check=True)
    head_before = git(repo.root, "rev-parse", "HEAD")
    proc = run_tasks(repo, "close", "nomerge", "--no-merge", env=base_env(TASKS_GATE_CMDS="false"))
    assert proc.returncode == 0, proc.stderr
    assert "kept branch nomerge (not merged)" in proc.stdout
    assert status_of(repo, "nomerge") == "done" and "closed (not merged)" in (repo.root / "tasks" / "done" / "0001-nomerge.md").read_text()
    assert not (repo.root / "kept.txt").exists() and git(repo.root, "rev-parse", "HEAD~1") == head_before
    assert git(repo.root, "rev-parse", "--verify", "refs/heads/nomerge")
    assert not wt.exists() and leases.load(repo, "nomerge") is None


def test_close_refuses_a_task_held_by_another_live_session(repo, other_session):
    _claimed(repo, "theirs")
    proc = run_tasks(repo, "close", "theirs", env=other_session("stranger"))
    assert proc.returncode == 4 and "held by live session test-session" in proc.stderr
    _assert_nothing_moved(repo, "theirs")


def test_close_of_an_already_done_task_retires_leftovers_only(repo):
    """Simulate a crash between the move-commit and retire: file in done/, branch+worktree+lease left."""
    _claimed(repo, "leaky")
    p = repo.root / "tasks" / "in_progress" / "0001-leaky.md"
    p.rename(repo.root / "tasks" / "done" / "0001-leaky.md")
    subprocess.run(["git", "add", "-A", "--", "tasks/"], cwd=repo.root, check=True)
    subprocess.run(["git", "commit", "-qm", "moved by hand"], cwd=repo.root, check=True)
    proc = run_tasks(repo, "close", "leaky")
    assert proc.returncode == 0 and "retiring leftovers only" in proc.stdout
    assert not (repo.root / ".worktrees" / "leaky").exists() and leases.load(repo, "leaky") is None
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "refs/heads/leaky"], cwd=repo.root).returncode != 0
    assert run_tasks(repo, "close", "leaky").returncode == 4  # nothing left: plain "already done"


def test_branch_moving_during_the_expensive_gate_is_refused(repo):
    _claimed(repo, "moving")
    wt = repo.root / ".worktrees" / "moving"
    (wt / "a.txt").write_text("a\n")
    subprocess.run(["git", "add", "a.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-qm", "a"], cwd=wt, check=True)
    # the "gate" itself commits to the branch, standing in for a concurrent push to it
    gate = f"git -C {wt} commit -q --allow-empty -m late"
    proc = run_tasks(repo, "close", "moving", env=base_env(TASKS_GATE_CMDS=gate))
    assert proc.returncode == 2 and "moved after the expensive gate ran" in proc.stderr
    _assert_nothing_moved(repo, "moving")


def test_retire_with_an_unremovable_worktree_never_claims_the_branch_is_unmerged(repo):
    from taskctl.close import _retire
    from taskctl.store import Store

    _claimed(repo, "stuck")
    wt = repo.root / ".worktrees" / "stuck"
    (wt / "wip.txt").write_text("uncommitted\n")  # makes `git worktree remove` (no --force) fail
    task = Store(repo).resolve("stuck")
    actions: list[str] = []
    _retire(repo, task, cancel=False, merged=True, force_worktree=False, actions=actions)
    text = "\n".join(actions)
    assert "KEPT worktree .worktrees/stuck" in text and "?? wip.txt" in text
    assert "kept branch stuck: its worktree is still registered (the merge itself landed)" in text
    assert "(not merged)" not in text
    assert wt.is_dir() and git(repo.root, "rev-parse", "--verify", "refs/heads/stuck")


def _with_work(repo, slug: str):
    _claimed(repo, slug)
    wt = repo.root / ".worktrees" / slug
    (wt / f"{slug}.txt").write_text("x\n")
    subprocess.run(["git", "add", f"{slug}.txt"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-qm", "work"], cwd=wt, check=True)


def _env_without_gate_override():
    env = base_env()
    env.pop("TASKS_GATE_CMDS")
    return env


def test_gate_cmds_file_in_main_checkout_is_the_gate(repo):
    (repo.root / "tasks" / "gate.cmds").write_text("# comment\n\ntrue\nfalse\n")
    git(repo.root, "add", "tasks/gate.cmds")
    git(repo.root, "commit", "-qm", "gate")
    _with_work(repo, "filegate")
    proc = run_tasks(repo, "close", "filegate", env=_env_without_gate_override())
    assert proc.returncode == 2 and "gate failed (1): false" in proc.stderr
    _assert_nothing_moved(repo, "filegate")


def test_no_gate_configured_lands_with_a_warning(repo):
    _with_work(repo, "nogate")
    proc = run_tasks(repo, "close", "nogate", env=_env_without_gate_override())
    assert proc.returncode == 0, proc.stderr
    assert "NOT verified" in proc.stdout
    assert status_of(repo, "nogate") == "done"

from _helpers import run_tasks

from taskctl import loopstate


def test_session_id_is_persisted_until_reset(repo):
    first = run_tasks(repo, "loop-state", "session").stdout.strip()
    assert first.startswith("loop-") and len(first) > 10
    assert run_tasks(repo, "loop-state", "session").stdout.strip() == first  # stable across calls
    assert loopstate.report(repo)["session"] == first
    # begin/record keep it
    loopstate.begin(repo, "x")
    loopstate.record(repo, "x", "stalled", "n")
    assert loopstate.session(repo) == first
    run_tasks(repo, "loop-state", "reset")
    second = run_tasks(repo, "loop-state", "session").stdout.strip()
    assert second != first

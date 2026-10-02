"""The within-pool comparator: one case per ranked path."""

from taskctl.order import sort_key
from taskctl.taskfile import Meta


def order(*items: tuple[Meta, float]) -> list[str]:
    return [m.title for m, _ in sorted(items, key=lambda it: sort_key(it[0], it[1]))]


def test_priority_beats_everything():
    a = Meta(title="p2-bug-user-old", type="bug", priority="p2", creator="user")
    b = Meta(title="p1-idea-zed-new", type="idea", priority="p1", creator="zed")
    assert order((a, 0.0), (b, 1e9)) == ["p1-idea-zed-new", "p2-bug-user-old"]


def test_type_rank_bug_task_spike_readback_chore_idea():
    metas = [Meta(title=t, type=t, priority="p2") for t in ("idea", "chore", "readback", "spike", "task", "bug")]
    assert order(*[(m, 0.0) for m in metas]) == ["bug", "task", "spike", "readback", "chore", "idea"]


def test_creator_user_first_then_alphabetical():
    metas = [Meta(title=c, type="task", priority="p2", creator=c) for c in ("triage", "agent", "user", "bob")]
    assert order(*[(m, 0.0) for m in metas]) == ["user", "agent", "bob", "triage"]


def test_age_older_first_as_final_tiebreak():
    a = Meta(title="new", type="task", priority="p2", creator="user")
    b = Meta(title="old", type="task", priority="p2", creator="user")
    assert order((a, 200.0), (b, 100.0)) == ["old", "new"]


def test_unknown_values_rank_as_defaults():
    weird = Meta(title="weird", type="nonsense", priority="p9", creator="user")
    normal = Meta(title="normal", type="task", priority="p2", creator="user")
    assert sort_key(weird, 0.0)[:2] == sort_key(normal, 0.0)[:2]

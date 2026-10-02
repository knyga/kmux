"""Fail-open header parsing and gates."""

from datetime import date

from _helpers import create, run_tasks

from taskctl.store import Store
from taskctl.taskfile import (
    append_progress,
    followup_problems,
    has_verdict,
    last_next_line,
    parse_header,
    unchecked_items,
)

HEADER = """# Fix the thing

type: {type}          # comment
priority: {priority}
creator: {creator}

Goal text here.

## Items
- [ ] 1. do it
"""


def test_header_parses_known_values():
    m = parse_header(HEADER.format(type="bug", priority="p0", creator="triage"))
    assert (m.title, m.type, m.priority, m.creator) == ("Fix the thing", "bug", "p0", "triage")
    assert m.warnings == []


def test_unknown_type_and_priority_fail_open_with_warning():
    m = parse_header(HEADER.format(type="bugg", priority="urgent", creator="user"), name="x.md")
    assert (m.type, m.priority) == ("task", "p2")
    assert len(m.warnings) == 2
    assert "unknown type 'bugg'" in m.warnings[0] and "unknown priority 'urgent'" in m.warnings[1]


def test_metadata_below_first_section_is_ignored():
    text = "# T\n\ntype: bug\n\n## Notes\ntype: idea\npriority: p0\n"
    m = parse_header(text)
    assert (m.type, m.priority) == ("bug", "p2")


def test_cli_prints_warning_but_keeps_task_in_queue(repo):
    p = create(repo, "typo-task")
    p.write_text(p.read_text().replace("type: task", "type: taks"))
    proc = run_tasks(repo, "index")
    assert proc.returncode == 0
    assert "typo-task" in proc.stdout and "task/p2/user" in proc.stdout
    assert "warning" in proc.stderr and "unknown type 'taks'" in proc.stderr


def test_sections_and_close_predicates():
    text = ("# T\n\n## Outcome\nMeasured 3 things.\n**Verdict:** shipped\n\n## Items\n- [x] 1. a\n- [ ] 2. b\n\n"
            "## Followups\n- [x] done one\n- promoted: tasks/*/0042-some-slug.md rename\n- wontfix: not worth it\n"
            "- dangling entry\n\n## Progress\n- 2026-09-01 started\n- 2026-09-02 NEXT: item 2\n")
    assert unchecked_items(text) == ["- [ ] 2. b"]
    assert has_verdict(text)
    assert followup_problems(text) == ["- dangling entry"]
    assert last_next_line(text) == "- 2026-09-02 NEXT: item 2"


def test_append_progress_lands_inside_section(tmp_path):
    p = tmp_path / "t.md"
    p.write_text("# T\n\n## Progress\n<!-- notes -->\n\n## Trailer\nx\n")
    append_progress(p, "- 2026-09-07 claimed")
    assert p.read_text() == "# T\n\n## Progress\n<!-- notes -->\n- 2026-09-07 claimed\n\n## Trailer\nx\n"
    q = tmp_path / "u.md"
    q.write_text("# T\n\nbody\n")
    append_progress(q, "- 2026-09-07 claimed")
    assert q.read_text().endswith("## Progress\n- 2026-09-07 claimed\n")


def _with_header_line(path, line):
    path.write_text(path.read_text().replace("creator: user\n", f"creator: user\n{line}\n"))


def test_gates_fail_open_and_report(repo, capsys):
    store = Store(repo)
    bad_date = create(repo, "bad-date")
    _with_header_line(bad_date, "blocked-until: someday")
    future = create(repo, "future")
    _with_header_line(future, "blocked-until: 2999-01-01")
    parent = create(repo, "parent")
    child_open = create(repo, "child-open")
    _with_header_line(child_open, "blocked-by: parent")
    finished = create(repo, "finished")
    child_done = create(repo, "child-done")
    _with_header_line(child_done, "blocked-by: 0005-finished")
    missing = create(repo, "child-missing")
    _with_header_line(missing, "blocked-by: nobody-here")
    # move "finished" to done/ by hand
    dst = repo.root / "tasks" / "done" / finished.name
    finished.rename(dst)

    tasks = store.load(quiet=True)
    by = {t.slug: t for t in tasks}
    today = date(2026, 9, 7)
    assert store.gate_reason(by["bad-date"], tasks, today) is None
    assert store.gate_reason(by["future"], tasks, today) == "blocked-until 2999-01-01"
    assert store.gate_reason(by["child-open"], tasks, today) == "blocked-by 0003-parent (todo)"
    assert store.gate_reason(by["child-done"], tasks, today) is None
    assert store.gate_reason(by["child-missing"], tasks, today) is None
    err = capsys.readouterr().err
    assert "blocked-until 'someday' is not a date" in err
    assert "blocked-by 'nobody-here' not found" in err
    assert parent.exists()


def test_picker_skips_gated_and_prints_it(repo):
    gated = create(repo, "gated", priority="p0")
    _with_header_line(gated, "blocked-until: 2999-01-01")
    create(repo, "free", priority="p3")
    proc = run_tasks(repo, "claim", "--json")
    assert proc.returncode == 0, proc.stderr
    assert '"slug": "free"' in proc.stdout
    assert "skipped (gated): tasks/todo/0001-gated.md — blocked-until 2999-01-01" in proc.stderr


def test_headings_inside_fences_do_not_start_sections():
    from taskctl.taskfile import sections

    text = "# T\n\ntype: bug\n\n## Items\n- [ ] 1. real\n\n```\n## Items\n- [ ] phantom\n```\n\n## Progress\n"
    assert list(sections(text)) == ["Items", "Progress"]
    assert unchecked_items(text) == ["- [ ] 1. real", "- [ ] phantom"]  # fenced text stays in Items
    fenced_header = "# T\n\n```\n## Not a section\n```\ntype: bug\n\n## Items\n"
    assert parse_header(fenced_header).type == "bug"


def test_misspelled_header_key_warns_loudly():
    m = parse_header("# T\n\nprioirty: p0\ntype: bug\n\n## Items\n", name="x.md")
    assert m.priority == "p2" and any("unknown header key 'prioirty'" in w for w in m.warnings)


def test_tilde_fences_and_mixed_fences_hide_headings():
    from taskctl.taskfile import sections

    text = "# T\n\n## Items\n- [ ] 1. real\n\n~~~\n## Phantom\n```\nstill inside the ~~~ fence\n~~~\n\n## Progress\n"
    assert list(sections(text)) == ["Items", "Progress"]


def test_claim_line_host_parses_with_spaces_in_session_and_legacy_shape():
    from taskctl.taskfile import last_claim_host

    new = "# T\n\n## Progress\n- 2026-09-08 claimed by loop run 3 on host=mac.local (mode=new)\n"
    legacy = "# T\n\n## Progress\n- 2026-09-07 claimed by abc123 on oldhost (mode=slug)\n"
    both = legacy + "- 2026-09-08 claimed by a b c on host=newhost (mode=resume)\n"
    assert last_claim_host(new) == "mac.local"
    assert last_claim_host(legacy) == "oldhost"
    assert last_claim_host(both) == "newhost"
    assert last_claim_host("# T\n\n## Progress\n- 2026-09-08 parked: x\n") is None

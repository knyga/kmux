"""Task file format: header metadata (fail open), sections, gate checks, Progress appends."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

TYPES = ("bug", "task", "spike", "readback", "chore", "idea")  # ranked, best first
TYPE_RANK = {t: i for i, t in enumerate(TYPES)}
PRIORITIES = ("p0", "p1", "p2", "p3")
DEFAULT_TYPE = "task"
DEFAULT_PRIORITY = "p2"
DEFAULT_CREATOR = "user"

FILENAME_RE = re.compile(r"^(?:(\d{4})-)?([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_META_RE = re.compile(r"^([a-z][a-z-]*):[ \t]*(.*)$")
_TOKEN_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_UNCHECKED_RE = re.compile(r"^\s*[-*]\s+\[ \]")
_CHECKED_RE = re.compile(r"^\s*[-*]\s+\[[xX]\]")
_ENTRY_RE = re.compile(r"^[-*]\s+")
_PROMOTED_RE = re.compile(r"promoted:\s*tasks/\*/\d{4}-[a-z0-9]+(?:-[a-z0-9]+)*\.md")
_WONTFIX_RE = re.compile(r"wontfix:\s*\S")
_VERDICT_RE = re.compile(r"\bVerdict:", re.IGNORECASE)
_DATE_LINE_RE = re.compile(r"^\s*[-*]\s+(\d{4}-\d{2}-\d{2})\b")
_CLAIM_HOST_RE = re.compile(r" on host=(\S+) \(mode=")  # current shape: host is unambiguous
_CLAIM_LEGACY_RE = re.compile(r"claimed by \S+ on (\S+) \(mode=")  # pre-round-2 lines (session had no spaces)
KNOWN_KEYS = {"type", "priority", "creator", "discovered-by", "blocked-until", "blocked-by"}
_KEY_TYPOS = {"typ", "types", "prio", "prioirty", "priorty", "priority-", "creater", "author", "owner",
              "discovered", "discoveredby", "blocked", "blockedby", "blocked-until-", "blocks"}


@dataclass
class Meta:
    title: str = ""
    type: str = DEFAULT_TYPE
    priority: str = DEFAULT_PRIORITY
    creator: str = DEFAULT_CREATOR
    discovered_by: str | None = None
    blocked_until: str | None = None
    blocked_by: str | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"type": self.type, "priority": self.priority, "creator": self.creator, "title": self.title}


def split_filename(name: str) -> tuple[int | None, str] | None:
    m = FILENAME_RE.match(name)
    if not m:
        return None
    idx = int(m.group(1)) if m.group(1) else None
    return idx, m.group(2)


def _headings(text: str):
    """Yield (is_heading, line) with ``## `` lines inside ``` fences NOT counted as headings."""
    fence: str | None = None  # the marker that opened the current fence (``` or ~~~), if any
    for line in text.splitlines():
        stripped = line.lstrip()
        marker = stripped[:3] if stripped[:3] in ("```", "~~~") else None
        if marker and fence is None:
            fence = marker
        elif marker and marker == fence:
            fence = None
        yield (fence is None and line.startswith("## ")), line


def header_region(text: str) -> str:
    lines = []
    for is_heading, line in _headings(text):
        if is_heading:
            break
        lines.append(line)
    return "\n".join(lines)


def _strip_comment(value: str) -> str:
    return re.sub(r"\s+#.*$", "", value).strip()


def parse_header(text: str, *, name: str = "") -> Meta:
    """Fail-open header parse: bad values warn and fall back to defaults; nothing ever raises."""
    meta = Meta()
    where = f"{name}: " if name else ""
    for line in header_region(text).splitlines():
        if line.startswith("# ") and not meta.title:
            meta.title = line[2:].strip()
            continue
        m = _META_RE.match(line)
        if not m:
            continue
        key, value = m.group(1), _strip_comment(m.group(2))
        if key not in KNOWN_KEYS:
            if key in _KEY_TYPOS:
                meta.warnings.append(f"{where}unknown header key {key!r} (did you mean one of {sorted(KNOWN_KEYS)}?); ignored")
            continue
        if key == "type":
            if value in TYPE_RANK:
                meta.type = value
            else:
                meta.warnings.append(f"{where}unknown type {value!r}; using {DEFAULT_TYPE!r}")
        elif key == "priority":
            if value in PRIORITIES:
                meta.priority = value
            else:
                meta.warnings.append(f"{where}unknown priority {value!r}; using {DEFAULT_PRIORITY!r}")
        elif key == "creator":
            if _TOKEN_RE.match(value):
                meta.creator = value
            else:
                meta.warnings.append(f"{where}bad creator {value!r}; using {DEFAULT_CREATOR!r}")
        elif key == "discovered-by":
            meta.discovered_by = value or None
        elif key == "blocked-until":
            meta.blocked_until = value or None
        elif key == "blocked-by":
            meta.blocked_by = value or None
    return meta


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None


def sections(text: str) -> dict[str, str]:
    """``## Name`` -> body (first occurrence wins)."""
    out: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for is_heading, line in _headings(text):
        if is_heading:
            if current is not None and current not in out:
                out[current] = "\n".join(buf)
            current, buf = line[3:].strip(), []
        elif current is not None:
            buf.append(line)
    if current is not None and current not in out:
        out[current] = "\n".join(buf)
    return out


def unchecked_items(text: str) -> list[str]:
    body = sections(text).get("Items", "")
    return [ln.strip() for ln in body.splitlines() if _UNCHECKED_RE.match(ln)]


def has_verdict(text: str) -> bool:
    body = sections(text).get("Outcome")
    return body is not None and any(_VERDICT_RE.search(ln) for ln in body.splitlines())


def followup_problems(text: str) -> list[str]:
    body = sections(text).get("Followups")
    if body is None:
        return []
    problems = []
    for ln in body.splitlines():
        if not _ENTRY_RE.match(ln):
            continue
        if _CHECKED_RE.match(ln) or _PROMOTED_RE.search(ln) or _WONTFIX_RE.search(ln):
            continue
        problems.append(ln.strip())
    return problems


def progress_lines(text: str) -> list[str]:
    body = sections(text).get("Progress", "")
    return [ln.rstrip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("<!--")]


def last_progress_date(text: str) -> date | None:
    latest: date | None = None
    for ln in progress_lines(text):
        m = _DATE_LINE_RE.match(ln)
        if m:
            d = parse_date(m.group(1))
            if d and (latest is None or d > latest):
                latest = d
    return latest


def last_claim_host(text: str) -> str | None:
    """Host named by the most recent ``claimed by <session> on <host> (mode=…)`` Progress line."""
    hosts = [m.group(1) for ln in progress_lines(text)
             if (m := _CLAIM_HOST_RE.search(ln) or _CLAIM_LEGACY_RE.search(ln))]
    return hosts[-1] if hosts else None


def last_next_line(text: str) -> str | None:
    hits = [ln for ln in progress_lines(text) if "NEXT:" in ln]
    return hits[-1] if hits else None


def append_progress(path: Path, line: str) -> None:
    text = path.read_text()
    lines = text.splitlines()
    idx = next((i for i, ln in enumerate(lines) if ln.strip() == "## Progress"), None)
    if idx is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["## Progress", line]
    else:
        end = next((i for i in range(idx + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        while end > idx + 1 and not lines[end - 1].strip():
            end -= 1
        lines.insert(end, line)
    path.write_text("\n".join(lines) + "\n")


def render_stub(title: str, *, type_: str, priority: str, creator: str,
                discovered_by: str | None = None, goal: str = "") -> str:
    head = [f"# {title}", "", f"type: {type_}", f"priority: {priority}", f"creator: {creator}"]
    if discovered_by:
        head.append(f"discovered-by: {discovered_by}")
    body = [
        "",
        goal or "<goal, 1-3 sentences>",
        "",
        "## Outcome",
        "<!-- filled DURING the work, the same turn a fact is measured. Verdict mandatory before close. -->",
        "",
        "## Items",
        "- [ ] 1. ...",
        "",
        "## Progress",
        "<!-- dated one-liners: heartbeat + handoff note -->",
        "",
    ]
    return "\n".join(head + body)

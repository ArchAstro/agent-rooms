"""Deterministic trajectory summary: the small facts a stream card renders.

A published trajectory bundle is ~2MB; nothing at read time should have to
fetch one to answer "how did this change go". This folds the bundle that is
already in memory at publish into a few hundred bytes of RAW COUNTS, and the
kit stamps them on a thread message as metadata. No model call, no judgment:
`prompts` is how many times a human typed, `tool_calls` is how many times the
agent acted, and what those numbers MEAN (autonomy, health) is decided at
read time by whoever renders them — the same fact/interpretation split the
work-shape signal uses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


def trajectory_summary(content: Mapping[str, Any]) -> dict[str, Any]:
    """Fold a bundle's JSON into the summary a trajectory post carries.

    Every field is a fact read straight off the bundle. Fields whose source
    material is absent are omitted rather than guessed, so a consumer can
    trust presence: if `minutes` is there, the events really carried
    timestamps.
    """
    counts = {"human_prompt": 0, "agent_message": 0,
              "tool_action": 0, "tool_result": 0}
    # Endpoints compare as PARSED instants, never as strings: a session
    # mixing "-08:00" and "Z" offsets would otherwise order lexically,
    # invert the span, and clamp to zero minutes.
    first: datetime | None = None
    last: datetime | None = None
    mixed_awareness = False
    for chapter in content.get("chapters") or []:
        for event in chapter.get("events") or []:
            kind = event.get("type")
            if kind in counts:
                counts[kind] += 1
            at = _instant(event.get("occurred_at"))
            if at is not None:
                try:
                    if first is None or at < first:
                        first = at
                    if last is None or at > last:
                        last = at
                except TypeError:
                    # Naive mixed with aware is unorderable. Skipping just
                    # this event would make the duration depend on event
                    # ORDER (review find); the honest answer is no duration
                    # at all. Absent means omitted, never guessed.
                    mixed_awareness = True

    if mixed_awareness:
        first = last = None

    out: dict[str, Any] = {
        "prompts": counts["human_prompt"],
        "agent_messages": counts["agent_message"],
        "tool_calls": counts["tool_action"],
    }

    minutes = _minutes_between(first, last)
    if minutes is not None:
        out["minutes"] = minutes

    # bool is a subclass of int in Python: `True` would sail through an
    # isinstance check and then be rejected by the TS reader, silently
    # dropping the whole chip (review find).
    def _count(value):
        return isinstance(value, int) and not isinstance(value, bool)

    subject = content.get("subject") or {}
    if _count(subject.get("pr_number")):
        out["pr"] = subject["pr_number"]
    if isinstance(subject.get("repository"), str) and subject["repository"]:
        out["repository"] = subject["repository"]
    if isinstance(subject.get("pr_url"), str) and subject["pr_url"]:
        out["pr_url"] = subject["pr_url"]

    stats = (content.get("patch") or {}).get("stats") or {}
    if all(_count(stats.get(k)) for k in ("files", "added", "deleted")):
        out["diff"] = {"files": stats["files"], "added": stats["added"],
                       "deleted": stats["deleted"]}

    # Tests ran during the session, as outcome counts. `passed 3, failed 1`
    # is a fact; whether that is healthy is the reader's call.
    tests: dict[str, int] = {}
    for test in content.get("tests") or []:
        outcome = test.get("outcome")
        if isinstance(outcome, str) and outcome:
            tests[outcome] = tests.get(outcome, 0) + 1
    if tests:
        out["tests"] = tests

    # Provenance from the first execution span: which harness and model did
    # the work, carried with the same values the bundle records.
    chapters = content.get("chapters") or []
    spans = (chapters[0].get("execution_spans") if chapters else None) or []
    span = spans[0] if spans else {}
    for field, key in (("harness", "harness"), ("model", "model"),
                       ("reasoning_effort", "reasoning_effort")):
        value = (span.get(field) or {}).get("value")
        if isinstance(value, str) and value:
            out[key] = value

    current = content.get("current") or {}
    if isinstance(current.get("capture_fidelity"), str):
        out["capture"] = current["capture_fidelity"]

    return out


def _instant(value: object) -> datetime | None:
    """Parse an event timestamp, or None when absent/unparseable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _minutes_between(first: datetime | None, last: datetime | None) -> int | None:
    if first is None or last is None:
        return None
    try:
        return max(0, round((last - first).total_seconds() / 60))
    except TypeError:
        return None  # naive mixed with aware endpoints

#!/usr/bin/env python3
"""A2: the kit folds a published trajectory into card-sized facts.

    python3 tests/test_trajectory_summary.py

A published bundle is ~2MB; the stream card must never fetch one. The
summary is a deterministic fold computed at publish, raw counts only:
`prompts` is how many times a human typed, `tool_calls` how many times the
agent acted. What those numbers mean is decided at read time. The fixture
below is bundle-shaped exactly per evidence/model.py json contracts
(event_id/sequence/type/summary/occurred_at, span provenance values,
patch stats), so a drift in either side breaks here.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "skills", "team-room")
sys.path.insert(0, KIT)
os.environ.setdefault("TEAM_ROOM_TRUST_SERVER", "1")
os.environ.setdefault("ROOM_JSON", os.path.join(HERE, "fixtures", "room.json"))

from evidence.summary import trajectory_summary  # noqa: E402
from room_post import _trajectory_line  # noqa: E402


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  , ' + detail) if detail else ''}")
    return ok


def event(seq, kind, at=None):
    return {"event_id": f"s:{seq}", "sequence": seq, "type": kind,
            "summary": "x", "data": {}, "execution_span_id": "s",
            "occurred_at": at}


BUNDLE = {
    "schema": "team-room-evidence/v1",
    "subject": {"key": "r#7", "repository": "ArchAstro/firstlanding",
                "pr_number": 8123,
                "pr_url": "https://github.com/ArchAstro/firstlanding/pull/8123",
                "base_ref": "main"},
    "current": {"complete": True, "capture_mode": "review_capsule",
                "capture_fidelity": "exact"},
    "chapters": [{
        "session_id": "s",
        "execution_spans": [{
            "id": "s",
            "harness": {"value": "claude", "source": "observed"},
            "model": {"value": "claude-opus-4-8", "source": "harness_reported"},
            "reasoning_effort": {"value": "high", "source": "harness_reported"},
        }],
        "events": [
            event(1, "human_prompt", "2026-08-01T10:00:00Z"),
            event(2, "agent_message", "2026-08-01T10:00:30Z"),
            event(3, "tool_action", "2026-08-01T10:01:00Z"),
            event(4, "tool_result", "2026-08-01T10:01:05Z"),
            event(5, "tool_action", "2026-08-01T10:20:00Z"),
            event(6, "tool_result", "2026-08-01T10:20:10Z"),
            event(7, "human_prompt", "2026-08-01T11:00:00Z"),
            event(8, "tool_action", "2026-08-01T11:30:00Z"),
            event(9, "agent_message", "2026-08-01T11:36:00Z"),
        ],
    }],
    "patch": {"text": "", "stats": {"files": 6, "added": 214, "deleted": 80}},
    "tests": [{"command": "vitest run", "outcome": "passed"},
              {"command": "mix test", "outcome": "passed"},
              {"command": "flaky suite", "outcome": "failed"}],
}


def test_counts_are_a_faithful_fold_of_the_events():
    s = trajectory_summary(BUNDLE)
    ok = (s["prompts"] == 2 and s["tool_calls"] == 3
          and s["agent_messages"] == 2 and s["minutes"] == 96)
    return check("prompts, tool calls and duration fold faithfully", ok, f"{s}")


def test_identity_and_provenance_ride_along():
    s = trajectory_summary(BUNDLE)
    ok = (s["pr"] == 8123 and s["repository"] == "ArchAstro/firstlanding"
          and s["model"] == "claude-opus-4-8" and s["harness"] == "claude"
          and s["reasoning_effort"] == "high" and s["capture"] == "exact"
          and s["diff"] == {"files": 6, "added": 214, "deleted": 80}
          and s["tests"] == {"passed": 2, "failed": 1})
    return check("pr, model, diff and test outcomes carried as facts", ok, f"{s}")


def test_absent_material_is_omitted_not_guessed():
    bare = {"chapters": [{"session_id": "s", "events": [
        event(1, "human_prompt"), event(2, "tool_action")]}]}
    s = trajectory_summary(bare)
    ok = (s["prompts"] == 1 and s["tool_calls"] == 1
          and "minutes" not in s and "diff" not in s and "model" not in s
          and "tests" not in s)
    return check("no timestamps means no minutes, absent means omitted", ok, f"{s}")


def test_the_plain_line_reads_like_a_sentence():
    line = _trajectory_line(trajectory_summary(BUNDLE))
    ok = ("PR #8123" in line and "3 tool calls" in line
          and "96 min" in line and "2 human prompts" in line
          and "+214" in line and line.startswith("✓ "))
    return check("the fallback line stands alone for card-less surfaces", ok, line)


def test_withheld_counts_are_absent_never_zero():
    # Two review rounds sharpened this boundary. Round one: the summary
    # must be derived from the policy-applied payload, or local-review
    # publishes exactly what the mode removed. Round two: even derived
    # correctly, "0 tool calls" for a session full of real activity is a
    # FALSE STATEMENT, not a redaction — withheld counts must be ABSENT.
    # This mirrors publish_pr's exact post-restriction logic.
    from evidence.policy import policy_for_mode, restrict_payload
    full = trajectory_summary(restrict_payload(BUNDLE, policy_for_mode("review_capsule")))
    policy = policy_for_mode("local-review")
    local = trajectory_summary(restrict_payload(BUNDLE, policy))
    if not policy.allow_trajectory:
        for k in ("tool_calls", "agent_messages", "minutes"):
            local.pop(k, None)
    if not policy.allow_prompts:
        local.pop("prompts", None)
    if policy.mode != "review_capsule":
        local["capture"] = policy.mode
    return check(
        "withheld counts vanish; the mode is named; full mode keeps facts",
        full["prompts"] > 0 and full["tool_calls"] > 0
        and "prompts" not in local and "tool_calls" not in local
        and local["capture"] == "local_review",
        f"full={full['prompts']}/{full['tool_calls']} local_keys={sorted(local)}",
    )


def test_mixed_timestamp_awareness_omits_duration_entirely():
    # Skipping only the unorderable event made the duration depend on
    # event ORDER (review find). Naive mixed with aware now yields no
    # duration at all: absent means omitted, never guessed.
    b = {"chapters": [{"events": [
        event(1, "human_prompt", "2026-08-01T00:00:00"),
        event(2, "tool_action", "2026-08-01T10:00:00Z"),
        event(3, "tool_result", "2026-08-01T00:01:00"),
    ]}]}
    got = trajectory_summary(b)
    return check(
        "naive+aware timestamps yield no duration, not a partial one",
        "minutes" not in got and got["tool_calls"] == 1,
        f"{got}",
    )


def test_booleans_are_not_counts():
    # bool subclasses int in Python, so `True` would pass an isinstance
    # check here and then be rejected by the TS reader, silently dropping
    # the whole diff chip (review find).
    got = trajectory_summary({"chapters": [], "patch": {"stats":
        {"files": 1, "added": True, "deleted": 0}}})
    return check("a boolean never counts as a number", "diff" not in got, f"{got}")


if __name__ == "__main__":
    results = [
        test_counts_are_a_faithful_fold_of_the_events(),
        test_identity_and_provenance_ride_along(),
        test_absent_material_is_omitted_not_guessed(),
        test_the_plain_line_reads_like_a_sentence(),
        test_withheld_counts_are_absent_never_zero(),
        test_mixed_timestamp_awareness_omits_duration_entirely(),
        test_booleans_are_not_counts(),
    ]
    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)

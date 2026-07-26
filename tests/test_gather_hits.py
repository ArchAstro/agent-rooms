#!/usr/bin/env python3
"""Regression tests for the room's read path.

    python3 tests/test_gather_hits.py

These need no network and no room: they replace the one function that talks to
the index, then assert what the caller is told. The bug they exist to prevent
shipped once — a session was told "nothing in the room, you're clear to
proceed" while the index was simply unreachable.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "team-room"))
os.environ.setdefault("TEAM_ROOM_TRUST_SERVER", "1")
os.environ.setdefault("ROOM_JSON", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "room.json"))

import room_post as rp  # noqa: E402


# A question with several distinctive terms, so gather_hits issues more than
# one probe (it searches the question as asked AND its key terms). A vaguer
# query would collapse to a single probe and the partial-failure case below
# could not be expressed.
MULTI_PROBE_QUERY = "slack response brake silence bot"


def _run(stub, query=MULTI_PROBE_QUERY):
    """Swap the index call for `stub`, run a search, restore."""
    original = rp.search_items
    rp.search_items = stub
    try:
        return rp.gather_hits(session={}, query=query)
    finally:
        rp.search_items = original


def test_unreachable_index_is_not_reported_as_silence():
    # "The room knows nothing" and "we could not ask the room" are opposite
    # facts. An agent told the first will proceed; it must not be told the
    # first when the second is true.
    def every_probe_fails(*_a, **_k):
        raise RuntimeError("index unreachable")

    try:
        _run(every_probe_fails)
    except RuntimeError:
        return "ok"
    raise AssertionError(
        "a fully unreachable index returned an empty result, which the caller "
        "renders as 'nothing in the room — you're clear to proceed'")


def test_genuine_no_match_still_reports_silence():
    # The opposite failure: if we raised on any empty result, every honest
    # "nothing here" would look like an outage and the room would cry wolf.
    assert _run(lambda *_a, **_k: []) == [], "a real no-match should stay empty"
    return "ok"


def test_partial_failure_still_returns_what_was_found():
    # One probe failing must not discard the other probe's hits — degraded
    # recall is fine, losing a real answer is not.
    calls = {"n": 0}

    def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first probe failed")
        return [{"id": "cim_1", "content": "a real hit"}]

    hits = _run(flaky)
    assert len(hits) == 1, f"expected the surviving probe's hit, got {hits}"
    return "ok"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:                       # noqa: BLE001
            failures += 1
            print(f"FAIL  {name}: {exc}")
    sys.exit(1 if failures else 0)

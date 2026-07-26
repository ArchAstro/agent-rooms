#!/usr/bin/env python3
"""Session-state and nudge behaviour.

    python3 tests/test_session_state.py

No network, no room. These pin the two things the nudge must get right: it
fires when a session is writing without ever reading, and it shuts up
otherwise. A tool that nags gets ignored, which is worse than silence.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "team-room"))
os.environ.setdefault("TEAM_ROOM_TRUST_SERVER", "1")
os.environ.setdefault("ROOM_JSON", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "room.json"))

import room_post as rp  # noqa: E402


def _fresh_state():
    """Point state at an empty temp file so tests never touch the real one.
    Also clear CI markers: the kit rightly silences nudges in CI, and these
    tests run in CI while testing the non-CI behavior."""
    rp.SESSION_STATE_PATH = os.path.join(tempfile.mkdtemp(), "sessions.json")
    for v in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "JENKINS_URL",
              "GITLAB_CI", "CIRCLECI", "TEAMCITY_VERSION"):
        os.environ.pop(v, None)


def test_writing_without_reading_is_called_out():
    # The measured failure: sessions post all day and never search, then
    # rediscover something the room already knew.
    _fresh_state()
    for _ in range(3):
        rp.record_session("post")
    msg = rp.session_nudge()
    assert "never asked the room" in msg, f"expected a read nudge, got {msg!r}"
    return "ok"


def test_a_session_that_searches_is_left_alone():
    _fresh_state()
    rp.record_session("search", topic="slack response brake", hits=4)
    for _ in range(3):
        rp.record_session("post")
    assert rp.session_nudge() == "", "a session that reads should not be nagged"
    return "ok"


def test_the_same_nudge_is_not_repeated():
    # Rate limiting is the difference between a useful signal and a linter
    # everyone disables.
    _fresh_state()
    for _ in range(3):
        rp.record_session("post")
    assert rp.session_nudge(), "first nudge should fire"
    assert rp.session_nudge() == "", "second nudge within the cooldown must not"
    return "ok"


def test_quiet_session_says_nothing():
    _fresh_state()
    rp.record_session("post")
    assert rp.session_nudge() == "", "one post is not a pattern worth nagging"
    return "ok"


def test_bookkeeping_never_breaks_a_command():
    # The room must never fail a post because of its own state file.
    _fresh_state()
    rp.SESSION_STATE_PATH = "/proc/nonexistent/cannot/write/sessions.json"
    rp.record_session("post")          # must not raise
    assert rp.session_nudge() == ""    # must not raise
    return "ok"


def test_nudge_reaches_a_coding_agent():
    # Coding agents invoke this through a subprocess pipe, so stderr is never a
    # tty. Gating on isatty() silenced the nudge for exactly the audience it
    # exists for — the feature was 100% dead in real use and the unit tests
    # could not see it.
    _fresh_state()
    for _ in range(3):
        rp.record_session("post")
    assert rp.session_nudge(), "nudge must fire for an agent on a piped stderr"
    return "ok"


def test_ci_is_not_nagged():
    _fresh_state()
    os.environ["CI"] = "true"
    try:
        for _ in range(3):
            rp.record_session("post")
        assert rp.session_nudge() == "", "CI has nobody reading; stay silent"
    finally:
        os.environ.pop("CI", None)
    return "ok"


def test_a_corrupt_state_file_does_not_break_pruning():
    # The file is hand-editable and shared; one non-dict value must not wedge
    # every future write.
    import json
    _fresh_state()
    os.makedirs(os.path.dirname(rp.SESSION_STATE_PATH), exist_ok=True)
    bad = {f"k{i}": {"last_at": i} for i in range(205)}
    bad["junk"] = "not-a-dict"
    with open(rp.SESSION_STATE_PATH, "w") as f:
        json.dump(bad, f)
    rp.record_session("post")          # must not raise
    return "ok"


def test_marathon_session_gets_renudged_after_reads_go_stale():
    # One early search must not immunize a long session: after 4 posts with
    # no further reading, the nudge fires again.
    _fresh_state()
    rp.record_session("search", topic="warmup")
    for _ in range(4):
        rp.record_session("post")
    msg = rp.session_nudge()
    assert "since you last read" in msg, msg
    print("PASS  test_marathon_session_gets_renudged_after_reads_go_stale")


def test_reading_resets_the_recency_counter():
    _fresh_state()
    rp.record_session("search", topic="warmup")
    for _ in range(3):
        rp.record_session("post")
    rp.record_session("read")
    rp.record_session("post")
    assert rp.session_nudge() == "", "one fresh read should quiet the nudge"
    print("PASS  test_reading_resets_the_recency_counter")


def test_an_assist_is_remembered_and_stamped_on_the_next_post():
    # The delight loop's data layer: a lesson hit -> session remembers ->
    # the next post credits the author, so the room can celebrate them.
    _fresh_state()
    rp._remember_assist({"id": "msg_LESSON1",
                         "metadata": {"human": "Rob", "post_type": "lesson"}})
    meta = rp.build_metadata("done", [])
    assert meta.get("assisted_by") == "msg_LESSON1", meta
    assert meta.get("assisted_author") == "Rob", meta
    print("PASS  test_an_assist_is_remembered_and_stamped_on_the_next_post")


def test_posts_carry_session_minutes():
    # The savings arithmetic's raw fact: how long into the session was this
    # post made. Lessons record discovery cost; dones record cycle time.
    _fresh_state()
    rp.record_session("search", topic="warmup")
    meta = rp.build_metadata("lesson", [])
    assert isinstance(meta.get("session_minutes"), int), meta
    print("PASS  test_posts_carry_session_minutes")


def test_posted_confirmation_line_never_crashes():
    # A NameError here once broke EVERY post and only the health ledger
    # noticed. The line must render for all verbs and for missing metadata.
    for md in ({"post_type": "lesson"}, {"post_type": "done"}, {}, None):
        line = rp._posted_line(md, {"id": "msg_x"})
        assert line.startswith("posted") and "msg_x" in line, line
    print("PASS  test_posted_confirmation_line_never_crashes")


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

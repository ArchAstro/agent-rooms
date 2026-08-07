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
import json
import contextlib
import io
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "team-room"))
os.environ.setdefault("TEAM_ROOM_TRUST_SERVER", "1")
os.environ.setdefault("ROOM_JSON", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "room.json"))

import room_post as rp  # noqa: E402


def test_repeated_health_event_increments_one_logical_row():
    original = rp.HEALTH_LOG_PATH
    try:
        rp.HEALTH_LOG_PATH = os.path.join(tempfile.mkdtemp(), "health.jsonl")
        rp.health_event("mirror:staging", "TimeoutError")
        rp.health_event("mirror:staging", "TimeoutError")
        with open(rp.HEALTH_LOG_PATH) as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        assert len(rows) == 1, rows
        assert rows[0]["count"] == 2, rows
    finally:
        rp.HEALTH_LOG_PATH = original
    return "ok"


def test_optional_mirrors_never_block_the_post():
    """The old contract was a shared 1-second inline deadline; the new one
    is stronger: posting performs NO mirror network work at all. It appends
    one self-describing line to the queue and spawns a detached worker —
    even a mirror that would hang forever cannot slow a post."""
    import tempfile as _tempfile

    real_mirrors = rp.MIRRORS
    real_queue = rp.MIRROR_QUEUE_PATH
    real_http = rp.http_json
    real_popen = rp.subprocess.Popen
    try:
        rp.MIRRORS = [
            {
                "name": f"slow-{index}",
                "server": "https://mirror.invalid",
                "portal": "https://mirror.invalid",
                "app_slug": "room",
                "thread_id": "thread",
            }
            for index in range(3)
        ]
        rp.MIRROR_QUEUE_PATH = os.path.join(
            _tempfile.mkdtemp(), "mirror-queue.jsonl"
        )

        def hang_forever(*_args, **_kwargs):
            raise AssertionError("posting must never touch a mirror inline")

        rp.http_json = hang_forever
        spawned = []
        rp.subprocess.Popen = lambda *a, **k: spawned.append(a[0]) or None
        output = io.StringIO()
        started = time.monotonic()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rp.mirror_fanout("message", {"post_type": "done"})
        elapsed = time.monotonic() - started
        assert elapsed < 0.15, elapsed
        assert output.getvalue() == "", output.getvalue()
        with open(rp.MIRROR_QUEUE_PATH) as handle:
            lines = [l for l in handle.read().splitlines() if l.strip()]
        assert len(lines) == 1, lines
        entry = json.loads(lines[0])
        assert {t["name"] for t in entry["targets"]} == {
            "slow-0", "slow-1", "slow-2"
        }
        assert len(spawned) == 1 and spawned[0][-1] == "mirror-flush"
    finally:
        rp.MIRRORS = real_mirrors
        rp.MIRROR_QUEUE_PATH = real_queue
        rp.http_json = real_http
        rp.subprocess.Popen = real_popen
    return "ok"


def test_expired_mirror_session_refreshes_inside_shared_budget():
    original_dir = rp.MIRRORS_DIR
    original_refresh = rp.refresh_session
    directory = tempfile.mkdtemp()
    mirror = {
        "name": "staging",
        "server": "https://mirror.invalid",
        "portal": "https://mirror.invalid",
        "app_slug": "room",
    }
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "staging.json"), "w") as handle:
        json.dump({
            "orgSessions": {
                "team": {
                    "accessToken": "expired",
                    "refreshToken": "refresh",
                    "expiresAt": 0,
                }
            }
        }, handle)
    observed = []

    def refresh(creds, key, path, **kwargs):
        observed.append(kwargs["timeout"])
        return {
            **creds["orgSessions"][key],
            "accessToken": "fresh",
            "appId": "app",
            "userId": "user",
            "expiresAt": int(time.time() * 1000) + 60_000,
        }

    try:
        rp.MIRRORS_DIR = directory
        rp.refresh_session = refresh
        session = rp._mirror_session(mirror, 0.2)
        assert session and session["accessToken"] == "fresh", session
        assert observed == [0.2], observed
    finally:
        rp.MIRRORS_DIR = original_dir
        rp.refresh_session = original_refresh
    return "ok"


def test_expired_mirror_without_refresh_token_emits_no_remediation():
    original_dir = rp.MIRRORS_DIR
    directory = tempfile.mkdtemp()
    mirror = {
        "name": "staging",
        "server": "https://mirror.invalid",
        "portal": "https://mirror.invalid",
        "app_slug": "room",
    }
    with open(os.path.join(directory, "staging.json"), "w") as handle:
        json.dump({
            "orgSessions": {
                "team": {"accessToken": "expired", "expiresAt": 0}
            }
        }, handle)
    output = io.StringIO()
    try:
        rp.MIRRORS_DIR = directory
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                rp._mirror_session(mirror, 0.05)
            except SystemExit:
                pass
        assert output.getvalue() == "", output.getvalue()
    finally:
        rp.MIRRORS_DIR = original_dir
    return "ok"


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


def test_real_post_path_surfaces_one_nudge_without_failing_the_post():
    # Integration boundary: main() used to calculate session_nudge() and drop
    # its return value. Pure function tests stayed green while no coding agent
    # ever received the reminder.
    _fresh_state()
    originals = {
        "post": rp.post,
        "advance": rp._advance_room_marker,
        "peek": rp.mention_peek,
        "mirror": rp.mirror_fanout,
        "argv": list(sys.argv),
    }
    rp.post = lambda *_args, **_kwargs: True
    rp._advance_room_marker = lambda: None
    rp.mention_peek = lambda: None
    rp.mirror_fanout = lambda *_args, **_kwargs: None
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            for number in range(3):
                sys.argv = ["room-post", "done", f"meaningful outcome {number}", "--no-meta"]
                rp.main()
    finally:
        rp.post = originals["post"]
        rp._advance_room_marker = originals["advance"]
        rp.mention_peek = originals["peek"]
        rp.mirror_fanout = originals["mirror"]
        sys.argv = originals["argv"]
    text = output.getvalue()
    assert text.count("never asked the room") == 1, text
    print("PASS  test_real_post_path_surfaces_one_nudge_without_failing_the_post")


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


def test_wrapper_does_not_invite_a_duplicate_after_a_late_failure():
    # A failure AFTER a successful send once produced "did NOT land" and
    # invited a duplicate repost. The non-disruptive wrapper now stays quiet
    # when it cannot distinguish a pre-send failure from a post-send failure.
    original_main = rp.main
    original_health = rp.health_event
    original_argv = list(sys.argv)
    output = io.StringIO()
    rp.main = lambda: (_ for _ in ()).throw(RuntimeError("after send"))
    rp.health_event = lambda *_args, **_kwargs: None
    sys.argv = ["room-post", "done", "already accepted"]
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                rp._run_never_blocking()
            except SystemExit as exc:
                assert exc.code == 0, exc.code
            else:
                raise AssertionError("soft-failure wrapper did not exit")
    finally:
        rp.main = original_main
        rp.health_event = original_health
        sys.argv = original_argv
    assert "did NOT land" not in output.getvalue(), output.getvalue()
    print("PASS  test_wrapper_does_not_invite_a_duplicate_after_a_late_failure")


def test_mention_matcher_finds_others_mentions_only():
    rows = [
        {"sender_name": "Rob Masson", "content": "@vivek can you review the deploy?",
         "created_at": "2026-07-26T15:00:00"},
        {"sender_name": "Vivek Sharma", "content": "@vivek self-note",
         "created_at": "2026-07-26T15:01:00"},
        {"sender_name": "Rob Masson", "content": "unrelated status post",
         "created_at": "2026-07-26T15:02:00"},
        {"sender_name": "Rob Masson", "content": "@vivek old ping",
         "created_at": "2026-07-20T09:00:00"},
    ]
    got = rp._fresh_mentions(rows, "vivek", "Vivek Sharma", since=1785000000)
    assert len(got) == 1 and "review the deploy" in got[0]["content"], got
    print("PASS  test_mention_matcher_finds_others_mentions_only")


def test_mention_peek_is_throttled_per_worktree():
    # The write path must stay near-free in bursts: after one peek, the
    # next 3 minutes of posts skip the network entirely.
    _fresh_state()
    calls = []
    real = rp._http_json_short
    real_auth = rp.authed_session
    rp._http_json_short = lambda *a, **k: (calls.append(1), {"data": []})[1]
    rp.authed_session = lambda: (None, None, None, {"accessToken": "t", "appId": "a"})
    try:
        rp.record_session("post")
        rp.mention_peek()
        rp.mention_peek()
        rp.mention_peek()
    finally:
        rp._http_json_short = real
        rp.authed_session = real_auth
    assert len(calls) == 1, f"expected 1 network call, got {len(calls)}"
    print("PASS  test_mention_peek_is_throttled_per_worktree")


def test_mention_peek_survives_a_disconnected_machine():
    # authed_session die()s with SystemExit(3) when not connected — the
    # peek must swallow it or every post on a fresh machine crashes.
    # CI (credential-less) caught this; local creds masked it.
    _fresh_state()
    real = rp.authed_session
    def dies():
        raise SystemExit(3)
    rp.authed_session = dies
    try:
        rp.record_session("post")
        rp.mention_peek()   # must not raise
    finally:
        rp.authed_session = real
    print("PASS  test_mention_peek_survives_a_disconnected_machine")


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

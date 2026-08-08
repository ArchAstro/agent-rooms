#!/usr/bin/env python3
"""Machine exhaust is distinguishable from conversation at the HTTP boundary."""
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "skills", "team-room")
sys.path.insert(0, KIT)
os.environ.setdefault("TEAM_ROOM_TRUST_SERVER", "1")
os.environ.setdefault("ROOM_JSON", os.path.join(HERE, "fixtures", "room.json"))

import room_post as rp  # noqa: E402


def test_only_conversational_verbs_remain_untyped():
    for post_type in ("handoff", "question", "notify", "approve"):
        assert rp.message_type_for({"post_type": post_type}) is None, post_type
    for post_type in ("start", "done", "lesson", "abandoned", "accept", "trajectory"):
        assert rp.message_type_for({"post_type": post_type}) == "exhaust", post_type
    assert rp.message_type_for(None) is None
    assert rp.message_type_for("invalid legacy metadata") is None


def test_primary_posts_stamp_exhaust_but_leave_conversation_untyped():
    sent = []
    rp.http_json = lambda url, body, **kwargs: sent.append(body) or {}
    session = {"accessToken": "token", "appId": "app", "userId": "user"}

    rp._post_once(session, "finished", {"post_type": "done"}, None)
    rp._post_once(session, "can you review?", {"post_type": "question"}, None)

    assert sent[0]["type"] == "exhaust", sent
    assert "type" not in sent[1], sent


def test_mirror_posts_preserve_the_same_participation_boundary():
    sent = []
    rp._trusted_servers = lambda: {"https://mirror.example"}
    rp.http_json = lambda url, body, **kwargs: sent.append(body) or {}
    target = {
        "name": "mirror",
        "server": "https://mirror.example",
        "thread_id": "thread",
    }
    sessions = {
        "mirror": {"accessToken": "token", "appId": "app", "userId": "user"}
    }

    assert rp._deliver_to_target(
        target,
        {"key": "one", "message": "built", "metadata": {"post_type": "trajectory"}},
        sessions,
        1,
    )
    assert rp._deliver_to_target(
        target,
        {"key": "two", "message": "please take this", "metadata": {"post_type": "handoff"}},
        sessions,
        1,
    )

    assert sent[0]["type"] == "exhaust", sent
    assert "type" not in sent[1], sent


def test_cli_keeps_protocol_type_when_optional_enrichment_fails():
    captured = []

    def fail_metadata(*_args, **_kwargs):
        raise RuntimeError("optional git enrichment failed")

    rp.build_metadata = fail_metadata
    rp.post = lambda message, metadata=None, uploads=None: captured.append(metadata) or True
    rp.mirror_fanout = lambda *_args, **_kwargs: None
    rp._advance_room_marker = lambda: None
    rp.record_session = lambda *_args, **_kwargs: None
    rp.session_nudge = lambda *_args, **_kwargs: None
    original_argv = sys.argv
    try:
        sys.argv = [rp.__file__, "done", "finished the work"]
        rp.main()
    finally:
        sys.argv = original_argv

    assert len(captured) == 1 and captured[0]["post_type"] == "done", captured
    assert rp.message_type_for(captured[0]) == "exhaust"


if __name__ == "__main__":
    test_only_conversational_verbs_remain_untyped()
    test_primary_posts_stamp_exhaust_but_leave_conversation_untyped()
    test_mirror_posts_preserve_the_same_participation_boundary()
    test_cli_keeps_protocol_type_when_optional_enrichment_fails()
    print("PASS  Room exhaust type keeps participate routines conversational")

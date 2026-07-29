#!/usr/bin/env python3
"""Focused native and generic adapter contracts.

Run with: python3 tests/test_pr_evidence_adapters.py
"""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "team-room"))

from evidence.adapters import select_adapter  # noqa: E402
from evidence.adapters.claude import ClaudeAdapter  # noqa: E402
from evidence.adapters.codex import CodexAdapter  # noqa: E402
from evidence.adapters.first_party import FirstPartyAdapter  # noqa: E402
from evidence.adapters.generic import GenericAdapter  # noqa: E402
from evidence.model import UNKNOWN  # noqa: E402


def write(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


def test_explicit_native_sessions_never_choose_the_newest_transcript():
    # A wrong newest-file branch would turn an unrelated session into PR evidence.
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        codex_home = root / "codex"
        claude_home = root / "claude"
        write(codex_home / "sessions" / "wanted-session.jsonl", [
            {"type": "session_meta", "payload": {"id": "wanted-session"}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Codex wanted"}]}},
        ])
        write(codex_home / "sessions" / "newest-session.jsonl", [
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Codex newest and wrong"}]}},
        ])
        write(claude_home / "projects" / "wanted-claude.jsonl", [
            {"type": "user", "sessionId": "wanted-claude", "message": {"content": "Claude wanted"}},
        ])
        write(claude_home / "projects" / "newest-claude.jsonl", [
            {"type": "user", "sessionId": "newest-claude", "message": {"content": "Claude newest and wrong"}},
        ])

        codex = CodexAdapter()
        codex_detection = codex.detect({"CODEX_THREAD_ID": "wanted-session", "CODEX_HOME": str(codex_home)}, root)
        assert codex_detection is not None
        assert [event.summary for event in codex.iter_events(codex.resolve_session(codex_detection, None), None)] == ["Codex wanted"]

        claude = ClaudeAdapter()
        claude_detection = claude.detect({"CLAUDE_SESSION_ID": "wanted-claude", "CLAUDE_HOME": str(claude_home)}, root)
        assert claude_detection is not None
        assert [event.summary for event in claude.iter_events(claude.resolve_session(claude_detection, None), None)] == ["Claude wanted"]
        print("PASS  test_explicit_native_sessions_never_choose_the_newest_transcript")


def test_multiple_native_harnesses_require_an_explicit_choice():
    env = {"CODEX_THREAD_ID": "codex-active", "CLAUDE_SESSION_ID": "claude-active"}
    try:
        select_adapter(env, Path.cwd())
    except ValueError as exc:
        assert "--harness" in str(exc)
    else:
        raise AssertionError("multiple harnesses must not be guessed")
    assert isinstance(select_adapter(env, Path.cwd(), harness="codex"), CodexAdapter)
    print("PASS  test_multiple_native_harnesses_require_an_explicit_choice")


def test_generic_subprocess_gets_minimal_environment_and_stable_session_id():
    producer = ROOT / "tests" / "fixtures" / "evidence" / "generic-producer.py"
    adapter = GenericAdapter([sys.executable, str(producer)], deadline_seconds=2, stdout_limit=4096, stderr_limit=512)
    detection = adapter.detect({"HOST_SECRET": "must not leak"}, Path.cwd())
    assert detection is not None
    source = adapter.resolve_session(detection, "generic-active")
    events = list(adapter.iter_events(source, None))
    assert [(event.sequence, event.type, event.summary) for event in events] == [
        (1, "human_prompt", "Generic producer prompt"), (2, "test", "generic proof passed"),
    ]
    print("PASS  test_generic_subprocess_gets_minimal_environment_and_stable_session_id")


def test_spans_are_stable_and_missing_model_provenance_stays_unknown():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        home = root / "codex"
        write(home / "sessions" / "parent-session.jsonl", [
            {"type": "session_meta", "payload": {"id": "parent-session"}},
            {"type": "subagent_started", "id": "child-1", "parent_id": "parent-session"},
            {"type": "response_item", "span_id": "child-1", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "child visible result"}]}},
        ])
        adapter = CodexAdapter()
        detection = adapter.detect({"CODEX_THREAD_ID": "parent-session", "CODEX_HOME": str(home)}, root)
        assert detection is not None
        source = adapter.resolve_session(detection, None)
        spans = adapter.execution_spans(source)
        assert [(span.id, span.parent_id) for span in spans] == [("parent-session", None), ("child-1", "parent-session")]
        assert spans[0].model == UNKNOWN and spans[1].model == UNKNOWN
        assert list(adapter.iter_events(source, None))[0].execution_span_id == "child-1"
        print("PASS  test_spans_are_stable_and_missing_model_provenance_stays_unknown")


def test_real_shape_rollout_and_claude_blocks_preserve_only_visible_shareable_events():
    # These representative public shapes pin native-parser fidelity without using a private transcript.
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        codex_id = "0198c0de-1234-7abc-8def-0123456789ab"
        codex_home = root / "codex"
        rollout = codex_home / "sessions" / f"rollout-2026-07-28T12-00-00-{codex_id}.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_bytes((ROOT / "tests/fixtures/evidence/codex-rollout-real-shape.jsonl").read_bytes())
        codex = CodexAdapter()
        detection = codex.detect({"CODEX_THREAD_ID": codex_id, "CODEX_HOME": str(codex_home)}, root)
        assert detection is not None
        source = codex.resolve_session(detection, None)
        events = list(codex.iter_events(source, None))
        assert [event.type for event in events] == ["human_prompt", "agent_message", "tool_action", "tool_result", "tool_action", "tool_result", "tool_action", "tool_result", "tool_action"]
        assert [event.data.get("call_id") for event in events[2:4]] == ["call-1", "call-1"]
        span = codex.execution_spans(source)[0]
        assert span.model.value == "gpt-5.6-codex" and span.reasoning_effort.value == "high"

        claude_id = "8f1d8c7e-1234-4abc-8def-0123456789ab"
        claude_home = root / "claude"
        transcript = claude_home / "projects" / f"{claude_id}.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_bytes((ROOT / "tests/fixtures/evidence/claude-real-shape.jsonl").read_bytes())
        claude = ClaudeAdapter()
        detection = claude.detect({"CLAUDE_SESSION_ID": claude_id, "CLAUDE_HOME": str(claude_home)}, root)
        assert detection is not None
        events = list(claude.iter_events(claude.resolve_session(detection, None), None))
        assert [event.type for event in events] == ["human_prompt", "agent_message", "tool_action", "tool_result"]
        visible = "\n".join(event.summary for event in events)
        assert "hidden reasoning" not in visible and "meta prompt" not in visible
        assert events[-1].data["call_id"] == "tool-1"
        print("PASS  test_real_shape_rollout_and_claude_blocks_preserve_only_visible_shareable_events")


def test_native_session_paths_and_internal_metadata_are_hard_boundaries():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        home = root / "codex"
        session_id = "0198c0de-1234-7abc-8def-0123456789ab"
        write(home / "sessions" / f"rollout-a-{session_id}.jsonl", [{"type": "session_meta", "payload": {"id": "wrong-session-id"}}])
        adapter = CodexAdapter()
        detection = adapter.detect({"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(home)}, root)
        assert detection is not None
        try:
            adapter.resolve_session(detection, "../../outside")
        except ValueError:
            pass
        else:
            raise AssertionError("path traversal session IDs must be rejected")
        try:
            adapter.resolve_session(detection, None)
        except ValueError as exc:
            assert "metadata" in str(exc)
        else:
            raise AssertionError("metadata mismatch must be rejected")
        write(home / "sessions" / f"rollout-b-{session_id}.jsonl", [{"type": "session_meta", "payload": {"id": session_id}}])
        try:
            adapter.resolve_session(detection, None)
        except ValueError as exc:
            assert "uniquely" in str(exc)
        else:
            raise AssertionError("ambiguous rollout matches must be rejected")
        print("PASS  test_native_session_paths_and_internal_metadata_are_hard_boundaries")


def test_generic_rejects_session_mismatch_and_labels_evidence_self_reported():
    producer = ROOT / "tests" / "fixtures" / "evidence" / "generic-producer.py"
    adapter = GenericAdapter([sys.executable, str(producer)], deadline_seconds=2, stdout_limit=4096, stderr_limit=512)
    source = adapter.resolve_session(adapter.detect({}, Path.cwd()), "generic-active")
    assert adapter.execution_spans(source)[0].harness.source == "agent_reported"
    assert adapter.capture_fidelity == "self_reported"
    chapter, _ = adapter.chapter(source)
    assert chapter.capture_fidelity == "self_reported"
    mismatch = ROOT / "tests" / "fixtures" / "evidence" / "generic-mismatch-producer.py"
    bad = GenericAdapter([sys.executable, str(mismatch)], deadline_seconds=2)
    try:
        list(bad.iter_events(bad.resolve_session(bad.detect({}, Path.cwd()), "generic-active"), None))
    except ValueError as exc:
        assert "session ID" in str(exc)
    else:
        raise AssertionError("generic producer session mismatch must be rejected")
    print("PASS  test_generic_rejects_session_mismatch_and_labels_evidence_self_reported")


def test_first_party_capture_is_partial_and_round_prompts_precede_their_threads():
    session = "issue-fixer:owner/repository:42"
    capture = "\n".join(
        json.dumps(record)
        for record in [
            {"type": "issue_fixer_session", "session_id": session},
            {
                "type": "issue_fixer_prompt",
                "round": "fixer",
                "content": "Fix with TDD",
            },
            {
                "type": "codex_event",
                "round": "fixer",
                "event": {"type": "thread.started", "thread_id": "fixer-thread"},
            },
            {
                "type": "issue_fixer_prompt",
                "round": "verifier",
                "content": "Verify independently",
            },
            {
                "type": "codex_event",
                "round": "verifier",
                "event": {
                    "type": "thread.started",
                    "thread_id": "verifier-thread",
                },
            },
            {
                "type": "capture_omission",
                "round": "verifier",
                "omitted_events": 50,
                "omitted_bytes": 4096,
                "reason": "trajectory exceeded local evidence cap",
            },
        ]
    ).encode()
    adapter = FirstPartyAdapter("issue-fixer", capture)
    source = adapter.resolve_session(adapter.detect({}, Path.cwd()), session)
    chapter, _ = adapter.chapter(source)

    prompts = [event for event in chapter.events if event.type == "human_prompt"]
    assert adapter.capture_fidelity == "partial"
    assert chapter.capture_fidelity == "partial"
    assert [event.execution_span_id for event in prompts] == [session, session]
    assert [span.id for span in chapter.execution_spans] == [
        session,
        "fixer-thread",
        "verifier-thread",
    ]
    omission = next(event for event in chapter.events if event.type == "decision")
    assert omission.data["omitted_events"] == 50


def test_astrodev_bounded_capture_exposes_its_visible_trajectory_omission():
    session = "astrodev-session"
    capture = "\n".join(
        json.dumps(record)
        for record in [
            {"type": "session", "id": session},
            {
                "type": "message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "First prompt"}],
                },
            },
            {
                "type": "capture_omission",
                "omitted_bytes": 1_000_000,
                "reason": "middle trajectory omitted from bounded AstroDev capture",
            },
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Recent result"}],
                },
            },
        ]
    ).encode()
    adapter = FirstPartyAdapter("astrodev", capture)
    source = adapter.resolve_session(adapter.detect({}, Path.cwd()), session)
    chapter, _ = adapter.chapter(source)

    assert chapter.capture_fidelity == "partial"
    assert [event.type for event in chapter.events] == [
        "human_prompt",
        "decision",
        "agent_message",
    ]
    assert chapter.events[1].data["omitted_bytes"] == 1_000_000


def test_incremental_checkpoint_rebuilds_complete_chapter_and_ignores_partial_lines():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        session_id = "0198c0de-1234-7abc-8def-0123456789ab"
        path = root / "codex/sessions" / f"rollout-a-{session_id}.jsonl"
        path.parent.mkdir(parents=True)
        first = {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "first"}]}}
        second = {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "second"}]}}
        path.write_text(json.dumps({"type": "session_meta", "payload": {"id": session_id}}) + "\n" + json.dumps(first) + "\n" + json.dumps(second), encoding="utf-8")
        adapter = CodexAdapter()
        detection = adapter.detect({"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(root / "codex")}, root)
        assert detection is not None
        source = adapter.resolve_session(detection, None)
        events, checkpoint = adapter.read_events(source, None)
        assert [event.summary for event in events] == ["first"]  # trailing partial JSON is not durable yet
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        events, next_checkpoint = adapter.read_events(source, checkpoint)
        assert [event.summary for event in events] == ["first", "second"]
        assert next_checkpoint.normalized_state == ()  # checkpoint metadata never stores transcript bodies
        # Rewriting a byte before the saved offset invalidates append mode and rebuilds safely.
        path.write_text(path.read_text(encoding="utf-8").replace("first", "rewritten"), encoding="utf-8")
        events, _ = adapter.read_events(source, next_checkpoint)
        assert [event.summary for event in events] == ["rewritten", "second"]
        print("PASS  test_incremental_checkpoint_rebuilds_complete_chapter_and_ignores_partial_lines")


def test_checkpoint_never_persists_raw_transcript_and_accepts_bounded_large_records():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        session_id = "0198c0de-1234-7abc-8def-0123456789ab"
        path = root / "codex/sessions" / f"rollout-a-{session_id}.jsonl"
        path.parent.mkdir(parents=True)
        secret = "sk-proj-Ab_cd-efghijklmnop"
        huge = "x" * (70 * 1024)
        path.write_text("\n".join([json.dumps({"type": "session_meta", "payload": {"id": session_id}}), json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": secret + huge}]}})]) + "\n", encoding="utf-8")
        adapter = CodexAdapter()
        detection = adapter.detect({"CODEX_THREAD_ID": session_id, "CODEX_HOME": str(root / "codex")}, root)
        assert detection is not None
        events, checkpoint = adapter.read_events(adapter.resolve_session(detection, None), None)
        assert len(events) == 1 and len(events[0].summary) > 64 * 1024
        assert secret not in repr(checkpoint.normalized_state)
        assert sum(len(item) for item in checkpoint.normalized_state) <= 4096
        print("PASS  test_checkpoint_never_persists_raw_transcript_and_accepts_bounded_large_records")


def test_claude_requires_authoritative_session_metadata_and_codex_effort_field():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        claude_id = "8f1d8c7e-1234-4abc-8def-0123456789ab"
        path = root / "claude/projects" / f"{claude_id}.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"type": "user", "message": {"content": "no identity"}}) + "\n", encoding="utf-8")
        adapter = ClaudeAdapter()
        detection = adapter.detect({"CLAUDE_SESSION_ID": claude_id, "CLAUDE_HOME": str(root / "claude")}, root)
        assert detection is not None
        try:
            adapter.resolve_session(detection, None)
        except ValueError as exc:
            assert "metadata" in str(exc)
        else:
            raise AssertionError("Claude requires authoritative sessionId")
        print("PASS  test_claude_requires_authoritative_session_metadata_and_codex_effort_field")


if __name__ == "__main__":
    test_explicit_native_sessions_never_choose_the_newest_transcript()
    test_multiple_native_harnesses_require_an_explicit_choice()
    test_generic_subprocess_gets_minimal_environment_and_stable_session_id()
    test_spans_are_stable_and_missing_model_provenance_stays_unknown()
    test_real_shape_rollout_and_claude_blocks_preserve_only_visible_shareable_events()
    test_native_session_paths_and_internal_metadata_are_hard_boundaries()
    test_generic_rejects_session_mismatch_and_labels_evidence_self_reported()
    test_first_party_capture_is_partial_and_round_prompts_precede_their_threads()
    test_astrodev_bounded_capture_exposes_its_visible_trajectory_omission()
    test_incremental_checkpoint_rebuilds_complete_chapter_and_ignores_partial_lines()
    test_checkpoint_never_persists_raw_transcript_and_accepts_bounded_large_records()
    test_claude_requires_authoritative_session_metadata_and_codex_effort_field()

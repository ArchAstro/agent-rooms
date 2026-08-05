#!/usr/bin/env python3
"""End-to-end proof for the safe local PR-evidence artifact.

Run with: python3 tests/test_pr_evidence_bundle.py
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "team-room"))

from evidence.adapters.codex import CodexAdapter  # noqa: E402
from evidence.artifacts import validate_content  # noqa: E402
from evidence.bundle import build_bundle, git_evidence_from_repo  # noqa: E402
from evidence.bundle import GitEvidence  # noqa: E402
from evidence.model import Chapter, EvidenceEvent, ExecutionSpan, Patch, Subject  # noqa: E402


def git(*args, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "Evidence Test", "GIT_AUTHOR_EMAIL": "evidence@test.local",
             "GIT_COMMITTER_NAME": "Evidence Test", "GIT_COMMITTER_EMAIL": "evidence@test.local",
             "GIT_AUTHOR_DATE": "2026-07-28T12:00:00+0000", "GIT_COMMITTER_DATE": "2026-07-28T12:00:00+0000"},
    )
    return completed.stdout.strip()


def make_origin_and_clone(root: Path) -> tuple[Path, Path]:
    """A real origin and clone make the patch evidence an actual Git boundary."""
    origin = root / "origin"
    origin.mkdir()
    git("init", "-q", "-b", "main", cwd=origin)
    (origin / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "README.md", cwd=origin)
    git("commit", "-q", "-m", "base", cwd=origin)
    clone = root / "clone"
    git("clone", "-q", str(origin), str(clone), cwd=root)
    git("checkout", "-q", "-b", "feat/evidence", cwd=clone)
    return origin, clone


def test_exact_codex_session_becomes_safe_complete_current_json_artifact():
    # Setup: an explicit active session and a newer unrelated transcript coexist.
    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        _, clone = make_origin_and_clone(temp)
        base_sha = git("rev-parse", "HEAD", cwd=clone)
        (clone / "evidence.txt").write_text("captured patch\n", encoding="utf-8")
        git("add", "evidence.txt", cwd=clone)
        git("commit", "-q", "-m", "capture evidence", cwd=clone)
        head_sha = git("rev-parse", "HEAD", cwd=clone)

        codex_home = temp / "codex-home"
        sessions = codex_home / "sessions"
        sessions.mkdir(parents=True)
        fixture = ROOT / "tests" / "fixtures" / "evidence" / "codex-session.jsonl"
        shutil.copyfile(fixture, sessions / "codex-active.jsonl")
        # Its mtime and contents must never win selection over the explicit ID.
        (sessions / "codex-unrelated-newer.jsonl").write_text(
            json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": "UNRELATED NEWER TRANSCRIPT"}]}}) + "\n",
            encoding="utf-8",
        )

        # Boundary 1: resolve and stream the exact Codex transcript, not the newest file.
        adapter = CodexAdapter()
        detection = adapter.detect({"CODEX_THREAD_ID": "codex-active", "CODEX_HOME": str(codex_home)}, clone)
        assert detection is not None
        source = adapter.resolve_session(detection, None)
        events, next_checkpoint = adapter.read_events(source, None)
        chapter = Chapter.from_events("codex-active", events, adapter.execution_spans(source))

        # Boundary 2: bind those events to a real local Git diff and serialize one current artifact.
        subject = Subject(
            repository="github.com/acme/evidence", pr_number=17,
            pr_url="https://github.com/acme/evidence/pull/17", base_ref="main",
            base_sha=base_sha, merge_base_sha=base_sha, head_sha=head_sha,
        )
        result = build_bundle(
            subject, [chapter], git_evidence_from_repo(clone, base_sha, head_sha),
            {"output_dir": temp / "artifacts", "generated_at": "2026-07-28T12:00:10Z", "checkpoint": next_checkpoint},
        )

        # Observable result: the artifact is complete, canonical JSON, and its stated digest is real.
        payload = Path(result.path).read_bytes()
        artifact = json.loads(payload)
        assert result.complete is True
        assert result.size == len(payload)
        assert result.sha256 == hashlib.sha256(payload).hexdigest()
        assert result.next_checkpoint == next_checkpoint
        assert artifact["schema"] == "agent-room-pr-evidence/v1"
        assert artifact["current"]["complete"] is True
        assert artifact["subject"]["base_sha"] == base_sha
        assert artifact["subject"]["head_sha"] == head_sha

        # The literal human prompt, visible trajectory, exact patch, test, and observed model span survive.
        chapter_json = artifact["chapters"][0]
        assert chapter_json["prompts"] == ["Add a safe evidence bundle for this PR."]
        assert [event["type"] for event in chapter_json["events"]] == [
            "human_prompt", "agent_message", "tool_action", "tool_result",
        ]
        assert chapter_json["events"][2]["data"]["command"] == "python3 tests/test_pr_evidence_bundle.py"
        assert chapter_json["events"][3]["summary"].startswith("PASS focused bundle test")
        assert chapter_json["execution_spans"][0]["model"] == {
            "value": "gpt-5.6-codex", "source": "harness_reported",
        }
        assert artifact["patch"]["text"] == "diff --git a/evidence.txt b/evidence.txt\nnew file mode 100644\nindex 0000000..3c55434\n--- /dev/null\n+++ b/evidence.txt\n@@ -0,0 +1 @@\n+captured patch\n"
        assert artifact["tests"] == [{"command": "python3 tests/test_pr_evidence_bundle.py", "outcome": "passed"}]

        # Safety is observable in both structured JSON and the rendering.
        rendered = artifact["rendered_markdown"]
        serialized = payload.decode("utf-8")
        assert "sk_live_1234567890abcdef" not in serialized
        assert "SYSTEM TEXT MUST NEVER APPEAR" not in serialized
        assert "DEVELOPER TEXT MUST NEVER APPEAR" not in serialized
        assert "UNRELATED NEWER TRANSCRIPT" not in serialized
        assert "[REDACTED:authorization]" in serialized
        assert artifact["redactions"] == [
            {"category": "authorization", "count": 2},
            {"category": "bearer_token", "count": 1},
        ]
        assert "## Evidence for github.com/acme/evidence#17" in rendered
        assert "### Patch" in rendered and "### Tests" in rendered
        print("PASS  test_exact_codex_session_becomes_safe_complete_current_json_artifact")


def test_git_binding_completeness_and_test_outcomes_are_never_fabricated():
    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        _, clone = make_origin_and_clone(temp)
        base = git("rev-parse", "HEAD", cwd=clone)
        (clone / "one.txt").write_text("one\n", encoding="utf-8")
        git("add", "one.txt", cwd=clone)
        git("commit", "-q", "-m", "one", cwd=clone)
        head = git("rev-parse", "HEAD", cwd=clone)
        subject = Subject("github.com/acme/evidence", 18, None, "main", base, base, head)
        git_evidence = git_evidence_from_repo(clone, base, head)
        events = [
            EvidenceEvent("one", 1, "human_prompt", "Do the proof", {}),
            EvidenceEvent("two", 2, "tool_action", "exec_command", {"command": "python3 tests/test_paired.py", "call_id": "paired"}),
            EvidenceEvent("three", 3, "tool_result", "exit code: 0", {"call_id": "paired", "exit_code": 0}),
            EvidenceEvent("four", 4, "tool_action", "exec_command", {"command": "python3 tests/test_failed.py", "call_id": "failed"}),
            EvidenceEvent("five", 5, "tool_result", "exit code: 1", {"call_id": "failed", "exit_code": 1}),
            EvidenceEvent("six", 6, "tool_action", "exec_command", {"command": "python3 tests/test_unknown.py", "call_id": "unknown"}),
        ]
        chapter = Chapter.from_events("0198c0de-1234-7abc-8def-0123456789ab", events, [ExecutionSpan("0198c0de-1234-7abc-8def-0123456789ab")])
        result = build_bundle(subject, [chapter], git_evidence, {"output_dir": temp / "safe", "generated_at": "2026-07-28T12:00:10Z"})
        assert json.loads(Path(result.path).read_text())["tests"] == [
            {"command": "python3 tests/test_paired.py", "outcome": "passed"},
            {"command": "python3 tests/test_failed.py", "outcome": "failed"},
            {"command": "python3 tests/test_unknown.py", "outcome": "attempted"},
        ]
        wrong = GitEvidence(git_evidence.patch, base, git_evidence.merge_base_sha, base)
        try:
            build_bundle(subject, [chapter], wrong, {"output_dir": temp / "wrong"})
        except ValueError as exc:
            assert "head" in str(exc)
        else:
            raise AssertionError("same merge-base evidence with wrong head must be rejected")
        empty = Chapter.from_events("empty-session", [], [ExecutionSpan("empty-session")])
        empty_result = build_bundle(subject, [empty], git_evidence, {"output_dir": temp / "empty"})
        assert empty_result.complete is False
        print("PASS  test_git_binding_completeness_and_test_outcomes_are_never_fabricated")


def test_size_cap_and_policy_strings_are_sanitized_before_atomic_persistence():
    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        subject = Subject("github.com/acme/evidence", 19, None, "main", "a" * 40, "a" * 40, "b" * 40)
        chapter = Chapter.from_events("cap-session", [
            EvidenceEvent("prompt", 1, "human_prompt", "Prompt", {}),
            EvidenceEvent("tool", 2, "tool_result", "ok", {"deep": [{"output": "x" * (4 * 1024 * 1024)}]}),
            EvidenceEvent("test", 3, "test", "proof", {"command": "proof", "outcome": "passed"}),
        ], [ExecutionSpan("cap-session")])
        evidence = GitEvidence(Patch("diff --git a/a b/a\n", 1, 1, 0), "a" * 40, "a" * 40, "b" * 40)
        result = build_bundle(subject, [chapter], evidence, {"output_dir": temp / "artifact", "tool_excerpt_limit": 4 * 1024 * 1024, "max_bytes": 99 * 1024 * 1024})
        serialized = Path(result.path).read_bytes()
        assert len(serialized) <= 3 * 1024 * 1024
        assert result.complete is False and any(item.category == "tool_result" for item in result.omissions)
        try:
            build_bundle(subject, [chapter], evidence, {"output_dir": temp / "invalid", "capture_mode": "sk-proj-abcdefghijklmnop"})
        except ValueError as exc:
            assert "capture mode" in str(exc)
        else:
            raise AssertionError("structural policy enums must reject untrusted strings")
        print("PASS  test_size_cap_and_policy_strings_are_sanitized_before_atomic_persistence")


def test_non_test_tools_and_unknown_outcomes_cannot_make_bundle_complete():
    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        subject = Subject("github.com/acme/evidence", 20, None, "main", "a" * 40, "a" * 40, "b" * 40)
        chapter = Chapter.from_events("non-test-session", [
            EvidenceEvent("prompt", 1, "human_prompt", "Change a file", {}),
            EvidenceEvent("action", 2, "tool_action", "apply_patch", {"command": "*** patch", "call_id": "patch"}),
            EvidenceEvent("result", 3, "tool_result", "Done", {"call_id": "patch", "exit_code": 0}),
        ], [ExecutionSpan("non-test-session")])
        evidence = GitEvidence(Patch("diff --git a/a b/a\n", 1, 1, 0), "a" * 40, "a" * 40, "b" * 40)
        result = build_bundle(subject, [chapter], evidence, {"output_dir": temp / "artifact"})
        payload = json.loads(Path(result.path).read_text())
        assert payload["tests"] == [] and result.complete is False
        print("PASS  test_non_test_tools_and_unknown_outcomes_cannot_make_bundle_complete")


def test_only_anchored_native_test_runners_create_test_evidence_and_schema_domains_hold():
    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        subject = Subject("github.com/acme/evidence", 21, None, "main", "a" * 40, "a" * 40, "b" * 40)
        chapter = Chapter.from_events("anchored-session", [
            EvidenceEvent("p", 1, "human_prompt", "prove", {}),
            EvidenceEvent("cat", 2, "tool_action", "exec_command", {"command": "cat tests/fixture.txt", "call_id": "cat"}),
            EvidenceEvent("catr", 3, "tool_result", "exit code: 0", {"call_id": "cat", "exit_code": 0}),
            EvidenceEvent("test", 4, "tool_action", "exec_command", {"command": "python3 tests/test_real.py", "call_id": "test"}),
            EvidenceEvent("testr", 5, "tool_result", "exit code: 0", {"call_id": "test", "exit_code": 0}),
        ], [ExecutionSpan("anchored-session")])
        evidence = GitEvidence(Patch("diff --git a/a b/a\n", 1, 1, 0), "a" * 40, "a" * 40, "b" * 40)
        result = build_bundle(subject, [chapter], evidence, {"output_dir": temp / "artifact"})
        assert json.loads(Path(result.path).read_text())["tests"] == [{"command": "python3 tests/test_real.py", "outcome": "passed"}]
        try:
            Subject("github.com/acme/evidence", 21, None, "main", "short", "a" * 40, "b" * 40)
        except ValueError:
            pass
        else:
            raise AssertionError("short SHA must be rejected before emission")
        print("PASS  test_only_anchored_native_test_runners_create_test_evidence_and_schema_domains_hold")


def test_large_exact_evidence_stays_structured_while_the_human_preview_is_bounded():
    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        subject = Subject("github.com/acme/evidence", 22, None, "main", "a" * 40, "a" * 40, "b" * 40)
        exact_prompt = "Preserve the complete review evidence " + ("prompt context " * 11_000)
        exact_trajectory = "🧠" * 150_000
        exact_test_command = "python3 tests/test_pr_evidence_bundle.py " + ("--case exact-evidence " * 8_000)
        chapter = Chapter.from_events("large-patch-session", [
            EvidenceEvent("prompt", 1, "human_prompt", exact_prompt, {}),
            EvidenceEvent("agent", 2, "agent_message", exact_trajectory, {}),
            EvidenceEvent("test", 3, "test", "proof", {"command": exact_test_command, "outcome": "passed"}),
        ], [ExecutionSpan("large-patch-session")])
        exact_patch = "diff --git a/large b/large\n" + ("+complete evidence line\n" * 9_000)
        evidence = GitEvidence(Patch(exact_patch, 1, 9_000, 0), "a" * 40, "a" * 40, "b" * 40)

        result = build_bundle(subject, [chapter], evidence, {"output_dir": temp / "artifact"})
        payload = json.loads(Path(result.path).read_text())

        assert payload["patch"]["text"] == exact_patch
        assert payload["chapters"][0]["prompts"] == [exact_prompt]
        assert payload["chapters"][0]["events"][1]["summary"] == exact_trajectory
        assert payload["tests"][0]["command"] == exact_test_command
        assert len(payload["rendered_markdown"].encode("utf-8")) <= 96 * 1024
        assert "Full patch: `patch.text`" in payload["rendered_markdown"]
        validated = validate_content(payload, subject.key, "pr-evidence--acme-evidence--22")
        assert validated["chapters"][0]["prompts"] == [exact_prompt]
        assert validated["chapters"][0]["events"][1]["summary"] == exact_trajectory
        assert validated["tests"][0]["command"] == exact_test_command
        print("PASS  large exact evidence stays structured while the human preview is bounded")


def test_event_flood_windows_to_the_arc_instead_of_failing_the_publish():
    # A very long session (14k+ events) outgrows the size cap on event
    # metadata alone; the old ladder gave up with "artifact exceeds the
    # configured size policy after safe degradation" and the publish was
    # silently lost. The third tier must keep the first/last window, stamp
    # truthful full-session event_counts, record an explicit omission with
    # the dropped counts, and always fit.
    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        subject = Subject("github.com/acme/evidence", 21, None, "main", "a" * 40, "a" * 40, "b" * 40)
        flood = []
        for index in range(20_000):
            kind = ("human_prompt", "tool_action", "tool_result", "agent_message")[index % 4]
            flood.append(EvidenceEvent(f"event-{index}", index + 1, kind, f"event number {index} " + "detail " * 20, {}, None, f"2026-08-04T0{index % 10}:00:00Z"))
        chapter = Chapter.from_events("flood-session", flood, [ExecutionSpan("flood-session")])
        evidence = GitEvidence(Patch("diff --git a/a b/a\n", 1, 1, 0), "a" * 40, "a" * 40, "b" * 40)
        result = build_bundle(subject, [chapter], evidence, {"output_dir": temp / "artifact"})
        payload = json.loads(Path(result.path).read_text())
        assert len(Path(result.path).read_bytes()) <= 3 * 1024 * 1024
        [rendered] = payload["chapters"]
        assert 0 < len(rendered["events"]) < 20_000
        counts = rendered["event_counts"]
        assert counts["human_prompt"] == 5_000 and counts["tool_action"] == 5_000
        assert counts["tool_result"] == 5_000 and counts["agent_message"] == 5_000
        window_omissions = [item for item in payload["omissions"] if item["category"] == "event_window"]
        assert window_omissions and "kept" in window_omissions[-1]["reason"]
        # The kept window preserves the session's real endpoints.
        assert rendered["events"][0]["event_id"] == "event-0"
        assert rendered["events"][-1]["event_id"] == "event-19999"
        print("PASS  test_event_flood_windows_to_the_arc_instead_of_failing_the_publish")



if __name__ == "__main__":
    test_exact_codex_session_becomes_safe_complete_current_json_artifact()
    test_git_binding_completeness_and_test_outcomes_are_never_fabricated()
    test_size_cap_and_policy_strings_are_sanitized_before_atomic_persistence()
    test_non_test_tools_and_unknown_outcomes_cannot_make_bundle_complete()
    test_event_flood_windows_to_the_arc_instead_of_failing_the_publish()
    test_only_anchored_native_test_runners_create_test_evidence_and_schema_domains_hold()
    test_large_exact_evidence_stays_structured_while_the_human_preview_is_bounded()

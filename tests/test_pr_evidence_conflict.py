#!/usr/bin/env python3
"""Adversarial publisher contracts: current ordering, hostile input, recovery."""
import json
import os
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "team-room"))
os.environ.setdefault("TEAM_ROOM_TRUST_SERVER", "1")
os.environ.setdefault(
    "ROOM_JSON", str(Path(__file__).resolve().parent / "fixtures" / "room.json")
)
from evidence.artifacts import ArtifactValidationError, semantic_hash
from evidence.policy import Policy, policy_for_mode, restrict_payload
from evidence.publisher import Publisher, PublishRequest
from evidence.retry import save_retry
import evidence.retry as retry
import room_post


SHA_A = "a" * 40
SHA_B = "b" * 40


def full_content(head=SHA_A, session_id="session-one", subject_key="github.com/owner/repository#7"):
    return {
        "schema": "agent-room-pr-evidence/v1",
        "subject": {
            "key": subject_key,
            "repository": "github.com/owner/repository",
            "pr_number": 7,
            "pr_url": None,
            "base_ref": "main",
            "base_sha": SHA_A,
            "merge_base_sha": SHA_A,
            "head_sha": head,
        },
        "current": {
            "complete": False,
            "capture_mode": "review_capsule",
            "capture_fidelity": "exact",
            "generated_at": "2026-01-01T00:00:00Z",
        },
        "chapters": [{
            "session_id": session_id,
            "capture_fidelity": "exact",
            "prompts": [],
            "events": [],
            "execution_spans": [],
        }],
        "patch": {"text": "", "stats": {"files": 0, "added": 0, "deleted": 0}},
        "tests": [],
        "provenance": {"adapter": {"value": "test", "source": "observed"}},
        "redactions": [],
        "omissions": [],
        "rendered_markdown": "",
    }


class ConflictClient:
    """Small real-client-shaped fake: one 409 must refetch/retry, two must queue."""
    def __init__(self, conflicts=0):
        self.conflicts = conflicts; self.updated = 0
        self.artifact = {"id": "a1", "name": "pr-evidence--owner-repository--7--x", "version": 1, "file_name": "pr-evidence.json", "content_type": "application/json",
                         "content": full_content(session_id="session-other")}
    def list_artifacts(self): return [self.artifact]
    def create_artifact(self, *_): return self.artifact
    def show_artifact(self, _): return self.artifact
    def update_artifact(self, _, content, version):
        self.updated += 1
        if self.updated <= self.conflicts: raise RuntimeError("409 conflict")
        self.artifact = {**self.artifact, "version": version + 1, "content": content}
        return self.artifact
    def create_message(self, *_): return {"id": "m1"}
    def list_messages(self): return [{
        "content": "pr-evidence:initial:github.com/owner/repository#7",
        "idempotency_key": "pr-evidence:initial:github.com/owner/repository#7",
        "attachments": [{"id": self.artifact["id"], "type": "artifact"}],
    }]


class ResponseLossClient:
    def __init__(self): self.created = 0; self.message_calls = 0; self.artifact = None
    def list_artifacts(self): return [] if self.artifact is None else [self.artifact]
    def create_artifact(self, name, content):
        self.created += 1; self.artifact = {"id": "a2", "name": name, "version": 1, "file_name": "pr-evidence.json", "content_type": "application/json", "content": content}; return self.artifact
    def show_artifact(self, _): return self.artifact
    def list_messages(self): return []
    def create_message(self, *_):
        self.message_calls += 1
        if self.message_calls == 1: raise RuntimeError("response lost")
        return {"id": "m2"}


class ConcurrentRewriteClient(ConflictClient):
    def __init__(self): super().__init__(1); self.rewritten = False
    def show_artifact(self, _):
        if self.updated and not self.rewritten:
            self.rewritten = True
            subject = {**self.artifact["content"]["subject"], "head_sha": "c" * 40}
            self.artifact = {**self.artifact, "version": 2, "content": {**self.artifact["content"], "subject": subject}}
        return self.artifact


class AdvanceAfterUpdateClient(ConflictClient):
    """The server can advance after our CAS before we observe its response."""
    def __init__(self):
        super().__init__()
        self.versions = {1: self.artifact["content"]}

    def update_artifact(self, _, content, version):
        assert version == 1
        self.updated += 1
        self.versions[2] = content
        later = full_content("c" * 40, session_id="session-later")
        self.versions[3] = later
        self.artifact = {**self.artifact, "version": 3, "content": later}
        return {**self.artifact, "version": 2, "content": content}

    def show_artifact(self, _, version=None):
        if version is None:
            return self.artifact
        return {**self.artifact, "version": version, "content": self.versions[version]}


class SubstitutedUpdateResponseClient(ConflictClient):
    def __init__(self):
        super().__init__()
        self.substitute = None

    def update_artifact(self, _, content, version):
        self.updated += 1
        self.substitute = {**self.artifact, "id": "a2", "version": version + 1, "content": content}
        return self.substitute

    def show_artifact(self, artifact_id, version=None):
        if self.substitute is None:
            assert artifact_id == "a1"
            return self.artifact
        assert artifact_id == "a2"
        return self.substitute


class InitialAttachmentAdvanceClient(ConflictClient):
    """Advance the current pointer immediately after the attachment effect."""
    def __init__(self):
        super().__init__()
        self.message_calls = 0

    def list_messages(self):
        return []

    def create_message(self, *_):
        self.message_calls += 1
        self.artifact = {
            **self.artifact,
            "version": 2,
            "content": full_content("c" * 40, session_id="session-later"),
        }
        return {"id": "m-raced"}


class BadCreateClient(ResponseLossClient):
    def create_artifact(self, _name, _content):
        self.created += 1
        return {"id": "attacker", "name": "wrong", "version": "bad", "content": "hostile"}


def test_one_conflict_refetches_and_second_conflict_queues_sanitized_state():
    with tempfile.TemporaryDirectory() as td:
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_B, "session-one", full_content(SHA_B), is_fast_forward=True)
        one = Publisher(ConflictClient(1), Path(td) / "one.json", Policy(), ancestor=lambda _old, _new: True)
        result = one.publish(request); assert result.status == "updated", result
        assert one.client.updated == 2
        two = Publisher(ConflictClient(2), Path(td) / "two.json", Policy(), ancestor=lambda _old, _new: True)
        assert two.publish(request).status == "queued"
        retry_path = Path(td) / "pr-evidence-retry.json"
        saved = retry_path.read_text()
        assert "session" not in saved and SHA_B in saved
        two.client.conflicts = 0
        assert two.publish(request).status == "updated"
        assert request.subject_key not in json.loads(retry_path.read_text())
        print("PASS  one conflict retries once and second queues sanitized state")


def test_explicit_local_capture_mode_only_narrows_the_complete_default():
    local = policy_for_mode("local-review")
    assert not local.allow_prompts and not local.allow_trajectory and not local.allow_patch
    try:
        policy_for_mode("unknown")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown local capture mode was accepted")
    upload = restrict_payload({"subject": {"head_sha": SHA_B}, "chapters": [{"prompts": ["private prompt"], "events": [{"summary": "private trajectory"}]}], "patch": {"text": "private patch"}, "rendered_markdown": "private prompt private trajectory private patch"}, local)
    assert "private" not in json.dumps(upload)
    assert policy_for_mode(None) == Policy()
    print("PASS  explicit local capture mode only narrows the complete default")


def test_local_review_restricts_previously_stored_chapters_before_upload():
    def complete_content(session_id, prompt, trajectory, patch):
        content = full_content(session_id=session_id)
        content["chapters"][0]["prompts"] = [prompt]
        content["chapters"][0]["events"] = [{
            "event_id": f"{session_id}-event", "sequence": 1,
            "type": "agent_message", "summary": trajectory, "data": {},
        }]
        content["patch"]["text"] = patch
        content["rendered_markdown"] = f"{prompt}\n{trajectory}\n{patch}\n"
        return content

    with tempfile.TemporaryDirectory() as td:
        remote = complete_content("session-older", "older private prompt", "older private trajectory", "older private patch")
        local = complete_content("session-newer", "new private prompt", "new private trajectory", "new private patch")
        client = ConflictClient()
        client.artifact = {**client.artifact, "content": remote}
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_A, "session-newer", local)
        result = Publisher(client, Path(td) / "state.json", Policy(mode="local_review", allow_prompts=False, allow_trajectory=False, allow_patch=False)).publish(request)

        assert result.status == "updated", result
        stored = client.artifact["content"]
        rendered = json.dumps(stored)
        for private_value in ("older private prompt", "older private trajectory", "older private patch", "new private prompt", "new private trajectory", "new private patch"):
            assert private_value not in rendered
        assert [chapter["prompts"] for chapter in stored["chapters"]] == [[], []]
        assert [chapter["events"] for chapter in stored["chapters"]] == [[], []]
        assert stored["patch"]["text"] == ""
        assert stored["rendered_markdown"] == (
            "## Evidence for github.com/owner/repository#7\n\n"
            f"Head: `{SHA_A}`\n\n"
            "Capture mode: `local_review`\n"
        )
    print("PASS  local-review restricts older chapters before upload")


def test_local_review_cold_recovery_restricts_existing_artifact_before_announcement():
    with tempfile.TemporaryDirectory() as td:
        retained_secret = "sk_live_1234567890abcdef"
        remote = full_content(session_id="session-older")
        remote["chapters"][0]["prompts"] = ["cold recovery private prompt"]
        remote["chapters"][0]["events"] = [{
            "event_id": "older-event", "sequence": 1,
            "type": "agent_message", "summary": "cold recovery private trajectory", "data": {},
        }]
        remote["patch"]["text"] = "cold recovery private patch"
        remote["rendered_markdown"] = "cold recovery private prompt\ncold recovery private trajectory\ncold recovery private patch\n"
        remote["chapters"][0]["execution_spans"] = [{
            "id": "span-older", "harness": {"value": retained_secret, "source": "observed"},
            "model": {"value": retained_secret, "source": "observed"},
        }]
        remote["tests"] = [{"command": retained_secret, "outcome": "passed"}]
        remote["provenance"] = {"adapter": {"value": retained_secret, "source": "observed"}}
        client = ConflictClient()
        client.artifact = {**client.artifact, "content": remote}
        client.list_messages = lambda: []
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_A, "session-newer", full_content(session_id="session-newer"))
        result = Publisher(client, Path(td) / "state.json", Policy(mode="local_review", allow_prompts=False, allow_trajectory=False, allow_patch=False)).publish(request)

        assert result.status == "published", result
        stored = json.dumps(client.artifact["content"])
        assert "cold recovery private" not in stored
        assert retained_secret not in stored
        assert client.artifact["content"]["chapters"][0]["prompts"] == []
        assert client.artifact["content"]["chapters"][0]["events"] == []
        assert client.artifact["content"]["patch"]["text"] == ""
    print("PASS  local-review cold recovery restricts existing artifact")


def test_semantic_hash_ignores_timestamps_but_hostile_remote_artifact_is_rejected():
    first = {"schema": "agent-room-pr-evidence/v1", "current": {"generated_at": "2026-01-01T00:00:00Z"}, "chapters": []}
    second = {"schema": "agent-room-pr-evidence/v1", "current": {"generated_at": "2026-02-02T00:00:00Z"}, "chapters": []}
    assert semantic_hash(first) == semantic_hash(second)
    try:
        Publisher.validate_remote({"name": "wrong", "version": "nope", "content": "attacker"}, "expected", "subject")
    except ArtifactValidationError:
        pass
    else:
        raise AssertionError("hostile artifact accepted")
    print("PASS  semantic hash and hostile remote boundary")


def test_initial_message_response_loss_recovers_without_second_artifact_creation():
    with tempfile.TemporaryDirectory() as td:
        content = full_content()
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_A, "session-one", content)
        client = ResponseLossClient(); publisher = Publisher(client, Path(td) / "state.json", Policy())
        assert publisher.publish(request).status == "queued"
        assert publisher.publish(request).status == "published"
        assert client.created == 1 and client.message_calls == 2
        print("PASS  initial message response-loss recovery is idempotent")


def test_conflict_refetch_rechecks_head_order_and_never_overwrites_a_rewrite():
    with tempfile.TemporaryDirectory() as td:
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_B, "session-one", full_content(SHA_B))
        client = ConcurrentRewriteClient()
        result = Publisher(client, Path(td) / "state.json", Policy(), ancestor=lambda old, new: old == SHA_A and new == SHA_B).publish(request)
        assert result.status == "withheld", result
        assert client.artifact["content"]["subject"]["head_sha"] == "c" * 40
        print("PASS  conflict refetch rechecks concurrent rewritten head")


def test_cold_recovery_rejects_an_orphan_artifact_with_an_unrelated_head_before_side_effects():
    with tempfile.TemporaryDirectory() as td:
        client = ConflictClient()
        client.artifact = {**client.artifact, "content": full_content("c" * 40, session_id="orphan-session")}
        client.list_messages = lambda: []
        messages = []
        client.create_message = lambda *args: messages.append(args) or {"id": "m1"}
        state_path = Path(td) / "state.json"
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_B, "session-one", full_content(SHA_B))

        result = Publisher(client, state_path, Policy(), ancestor=lambda _old, _new: False).publish(request)

        assert result.status == "withheld", result
        assert client.updated == 0
        assert messages == []
        assert not state_path.exists()
        assert not (Path(td) / "pr-evidence-retry.json").exists()
        print("PASS  cold recovery refuses unrelated orphan before local state or message")


def test_cold_recovery_records_a_pending_initial_attachment_before_response_loss():
    with tempfile.TemporaryDirectory() as td:
        client = ConflictClient()
        client.artifact = {**client.artifact, "content": full_content(session_id="orphan-session")}
        client.list_messages = lambda: []
        client.create_message = lambda *_: (_ for _ in ()).throw(RuntimeError("response lost"))
        state_path = Path(td) / "state.json"
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_A, "session-one", full_content())

        assert Publisher(client, state_path, Policy()).publish(request).status == "queued"
        assert json.loads(state_path.read_text())[request.subject_key]["message_pending"] == "initial"
        print("PASS  cold recovery persists initial attachment intent before response loss")


def test_pending_initial_attachment_rechecks_a_rewritten_remote_head_before_side_effects():
    with tempfile.TemporaryDirectory() as td:
        client = ConflictClient()
        client.artifact = {**client.artifact, "content": full_content("c" * 40, session_id="session-later")}
        client.list_messages = lambda: []
        messages = []
        client.create_message = lambda *args: messages.append(args) or {"id": "m1"}
        state_path = Path(td) / "state.json"
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_B, "session-one", full_content(SHA_B))
        state_path.write_text(json.dumps({request.subject_key: {
            "artifact_id": "a1", "artifact_version": 1, "head_sha": SHA_A,
            "content_hash": semantic_hash(full_content()), "message_pending": "initial",
        }}))

        result = Publisher(client, state_path, Policy(), ancestor=lambda _old, _new: False).publish(request)

        assert result.status == "withheld", result
        assert messages == []
        assert json.loads(state_path.read_text())[request.subject_key]["message_pending"] == "initial"
        print("PASS  pending initial attachment refuses rewritten remote before side effects")


def test_initial_attachment_rechecks_the_current_pointer_before_recording_success():
    with tempfile.TemporaryDirectory() as td:
        client = InitialAttachmentAdvanceClient()
        client.artifact = {**client.artifact, "content": full_content(SHA_B, session_id="session-one")}
        state_path = Path(td) / "state.json"
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_B, "session-one", full_content(SHA_B))
        state_path.write_text(json.dumps({request.subject_key: {
            "artifact_id": "a1", "artifact_version": 1, "head_sha": SHA_B,
            "content_hash": semantic_hash(full_content(SHA_B)), "message_pending": "initial",
        }}))

        result = Publisher(client, state_path, Policy(), ancestor=lambda old, new: old == SHA_A and new == SHA_B).publish(request)

        assert result.status == "queued", result
        persisted = json.loads(state_path.read_text())[request.subject_key]
        assert client.message_calls == 1
        assert persisted["artifact_version"] == 1
        assert persisted["head_sha"] == SHA_B
        assert persisted["message_pending"] == "initial"
        print("PASS  initial attachment rechecks current pointer before success state")


def test_initial_marker_without_the_artifact_attachment_does_not_suppress_recovery():
    with tempfile.TemporaryDirectory() as td:
        client = ConflictClient()
        client.artifact = {**client.artifact, "content": full_content(session_id="orphan-session")}
        key = "pr-evidence:initial:github.com/owner/repository#7"
        client.list_messages = lambda: [{"content": f"spoof [{key}]", "idempotency_key": key, "attachments": [{"id": "other", "type": "artifact"}]}]
        messages = []
        client.create_message = lambda *args: messages.append(args) or {"id": "m1"}
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_A, "session-one", full_content())

        result = Publisher(client, Path(td) / "state.json", Policy()).publish(request)

        assert result.status == "published", result
        assert len(messages) == 1
        assert messages[0][2] == [{"id": "a1", "type": "artifact"}]
        print("PASS  marker without the matching artifact attachment is not adopted")


def test_update_response_cannot_substitute_a_different_artifact_id():
    with tempfile.TemporaryDirectory() as td:
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_B, "session-one", full_content(SHA_B))
        client = SubstitutedUpdateResponseClient()

        result = Publisher(client, Path(td) / "state.json", Policy(), ancestor=lambda old, new: old == SHA_A and new == SHA_B).publish(request)

        assert result.status == "queued", result
        print("PASS  update response cannot substitute a same-name artifact")


def test_post_update_race_records_the_exact_written_version_not_the_later_head():
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_B, "session-one", full_content(SHA_B))
        client = AdvanceAfterUpdateClient()

        result = Publisher(client, state_path, Policy(), ancestor=lambda old, new: old == SHA_A and new == SHA_B).publish(request)

        assert result.status == "updated", result
        persisted = json.loads(state_path.read_text())[request.subject_key]
        assert persisted["artifact_version"] == 2
        assert persisted["head_sha"] == SHA_B
        assert client.artifact["version"] == 3
        assert client.artifact["content"]["subject"]["head_sha"] == "c" * 40
        print("PASS  post-update race binds only the exact CAS version to its head")


def test_retry_eviction_keeps_the_most_recently_queued_subjects():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "retry.json"
        original = retry.time.time_ns
        retry.time.time_ns = lambda: 1
        try:
            for number in range(100, -1, -1):
                assert save_retry(path, {
                    "subject_key": f"subject-{number:03d}", "artifact_name": "artifact",
                    "head_sha": SHA_A, "content_hash": "hash", "reason": "test",
                })
        finally:
            retry.time.time_ns = original
        saved = json.loads(path.read_text())
        assert len(saved) == 100
        assert "subject-100" not in saved
        assert "subject-000" in saved
        print("PASS  retry eviction preserves the newest queued subjects")


def test_publication_enforces_the_narrower_policy_byte_cap_and_validates_create_response():
    with tempfile.TemporaryDirectory() as td:
        content = full_content()
        request = PublishRequest("github.com/owner/repository#7", "pr-evidence--owner-repository--7--x", SHA_A, SHA_A, "session-one", content)
        assert Publisher(ResponseLossClient(), Path(td) / "small.json", Policy(max_bytes=1)).publish(request).status == "withheld"
        bad = BadCreateClient(); assert Publisher(bad, Path(td) / "bad.json", Policy()).publish(request).status == "queued"
        assert bad.message_calls == 0
        print("PASS  policy byte cap and create response boundary")


def test_same_name_artifact_in_another_team_or_thread_is_never_adopted():
    artifact = {"id": "a", "name": "expected", "version": 1, "team": "wrong-team", "thread": "wrong-thread", "file_name": "pr-evidence.json", "content_type": "application/json",
                "content": full_content(subject_key="subject")}
    for field, value in (("team", "team"), ("thread", "thread")):
        hostile = {**artifact, field: value}
        try: Publisher.validate_remote(hostile, "expected", "subject", "team", "thread")
        except ArtifactValidationError: pass
        else: raise AssertionError("cross-scope artifact was adopted")
    print("PASS  same-name remote artifact must match configured team and thread")


def test_discovery_writes_room_identity_without_deferred_evidence_configuration():
    with tempfile.TemporaryDirectory() as td:
        original = room_post.ROOM_CONFIG_PATH
        try:
            room_post.ROOM_CONFIG_PATH = str(Path(td) / "room.json")
            room_post._write_room_json("team", "thread", "https://example.invalid", "pk")
            configured = json.loads(Path(room_post.ROOM_CONFIG_PATH).read_text())
        finally:
            room_post.ROOM_CONFIG_PATH = original
        assert configured == {
            "thread_id": "thread",
            "team_id": "team",
            "server": "https://example.invalid",
            "portal": room_post.DEFAULT_PORTAL,
            "app_slug": room_post.DEFAULT_APP_SLUG,
            "publishable_key": "pk",
        }
    print("PASS  discovery writes room identity without deferred evidence configuration")


def test_hostile_schema_matrix_rejects_malformed_nested_chapters_events_and_spans():
    valid = full_content(subject_key="subject")
    for mutate in (
        lambda x: x["current"].__setitem__("complete", "yes"),
        lambda x: x.pop("patch"),
        lambda x: x.__setitem__("attacker", True),
        lambda x: x["chapters"][0].pop("prompts"),
        lambda x: x["chapters"][0].__setitem__("events", "attack"),
        lambda x: x["chapters"][0].__setitem__("events", [{"event_id": "e", "sequence": 1, "type": "attack", "summary": "", "data": {}}]),
        lambda x: x["chapters"][0].__setitem__("events", [{"event_id": "e", "type": "test", "summary": "", "data": {}}]),
        lambda x: x["chapters"][0].__setitem__("execution_spans", [{"id": 7}]),
        lambda x: x.__setitem__("tests", "attack"),
        lambda x: x.__setitem__("tests", [7]),
        lambda x: x.__setitem__("provenance", {"adapter": "attack"}),
        lambda x: x.__setitem__("redactions", [{"category": "secret", "count": "one"}]),
        lambda x: x.__setitem__("omissions", [7]),
        lambda x: x.__setitem__("rendered_markdown", ["attack"]),
    ):
        hostile = json.loads(json.dumps(valid)); mutate(hostile)
        try: Publisher.validate_remote({"id":"a", "name":"expected", "version":1, "file_name":"pr-evidence.json", "content_type":"application/json", "content":hostile}, "expected", "subject")
        except ArtifactValidationError: pass
        else: raise AssertionError("hostile nested schema accepted")
    print("PASS  hostile nested schema matrix")


def test_merge_preserves_remote_safety_evidence_and_canonical_tool_test_results():
    remote = full_content(session_id="session-old")
    remote["redactions"] = [{"category": "credential", "count": 4}]
    remote["omissions"] = [{"category": "tool_result", "reason": "size policy"}]
    local = full_content(session_id="session-new")
    local["chapters"][0]["events"] = [
        {
            "event_id": "action",
            "sequence": 1,
            "type": "tool_action",
            "summary": "exec_command",
            "data": {"call_id": "call-1", "command": "pytest tests/test_safe.py"},
        },
        {
            "event_id": "result",
            "sequence": 2,
            "type": "tool_result",
            "summary": "finished",
            "data": {"call_id": "call-1", "exit_code": 0},
        },
    ]
    merged = Publisher._merge(remote, local, "session-new")
    assert merged["redactions"] == [{"category": "credential", "count": 4}]
    assert merged["omissions"] == [{"category": "tool_result", "reason": "size policy"}]
    assert merged["tests"] == [{"command": "pytest tests/test_safe.py", "outcome": "passed"}]
    assert merged["current"]["complete"] is False
    print("PASS  merge preserves safety evidence and canonical inferred tests")


if __name__ == "__main__":
    test_one_conflict_refetches_and_second_conflict_queues_sanitized_state()
    test_explicit_local_capture_mode_only_narrows_the_complete_default()
    test_local_review_restricts_previously_stored_chapters_before_upload()
    test_local_review_cold_recovery_restricts_existing_artifact_before_announcement()
    test_semantic_hash_ignores_timestamps_but_hostile_remote_artifact_is_rejected()
    test_initial_message_response_loss_recovers_without_second_artifact_creation()
    test_conflict_refetch_rechecks_head_order_and_never_overwrites_a_rewrite()
    test_cold_recovery_rejects_an_orphan_artifact_with_an_unrelated_head_before_side_effects()
    test_cold_recovery_records_a_pending_initial_attachment_before_response_loss()
    test_pending_initial_attachment_rechecks_a_rewritten_remote_head_before_side_effects()
    test_initial_attachment_rechecks_the_current_pointer_before_recording_success()
    test_initial_marker_without_the_artifact_attachment_does_not_suppress_recovery()
    test_update_response_cannot_substitute_a_different_artifact_id()
    test_post_update_race_records_the_exact_written_version_not_the_later_head()
    test_retry_eviction_keeps_the_most_recently_queued_subjects()
    test_publication_enforces_the_narrower_policy_byte_cap_and_validates_create_response()
    test_same_name_artifact_in_another_team_or_thread_is_never_adopted()
    test_discovery_writes_room_identity_without_deferred_evidence_configuration()
    test_hostile_schema_matrix_rejects_malformed_nested_chapters_events_and_spans()
    test_merge_preserves_remote_safety_evidence_and_canonical_tool_test_results()

"""Bounded artifact identity, encoding, and hostile-current validation."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

MAX_RAW_BYTES = 3 * 1024 * 1024
MAX_BASE64_BYTES = 4 * 1024 * 1024
MAX_NESTED_STRING_CHARS = 131_072


class ArtifactValidationError(ValueError):
    pass


@dataclass(frozen=True)
class EncodingStats:
    raw_bytes: int
    base64_bytes: int


def deterministic_name(repository: str, pr_number: int) -> str:
    slug = repository.removeprefix("github.com/").replace("/", "-")
    digest = hashlib.sha256((repository + "\n" + str(pr_number)).encode()).hexdigest()[:16]
    return f"pr-evidence--{slug}--{pr_number}--{digest}"


def _semantic(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _semantic(v) for k, v in value.items() if k not in {"generated_at", "updated_at", "created_at", "transport_timestamp"}}
    if isinstance(value, list):
        return [_semantic(v) for v in value]
    return value


def semantic_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(_semantic(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def encode_artifact(raw: bytes) -> tuple[bytes, EncodingStats]:
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("artifact exceeds the 3 MiB raw content limit")
    encoded = base64.b64encode(raw)
    if len(encoded) > MAX_BASE64_BYTES:
        raise ValueError("artifact exceeds the 4 MiB Base64 content limit")
    return encoded, EncodingStats(len(raw), len(encoded))


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{40,64}", value))


def validate_content(content: object, subject_key: str, expected_name: str) -> dict[str, Any]:
    if not isinstance(content, Mapping):
        raise ArtifactValidationError("remote artifact content must be an object")
    # Re-encode before inspecting nested data so an attacker cannot hand the
    # client an unbounded object disguised as decoded JSON.
    try:
        raw = json.dumps(content, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise ArtifactValidationError("remote artifact content is not strict JSON") from exc
    if len(raw) > MAX_RAW_BYTES or content.get("schema") != "agent-room-pr-evidence/v1":
        raise ArtifactValidationError("remote artifact has invalid size or schema")
    def bounded(value: Any, depth: int = 0, path: tuple[str, ...] = ()) -> None:
        if depth > 20: raise ArtifactValidationError("remote artifact nesting exceeds limit")
        if isinstance(value, str):
            # The exact patch and legacy human rendering can legitimately be
            # larger than an ordinary leaf. The full serialized artifact is
            # already bounded above, so allow only these named evidence fields
            # to consume that envelope. New renderings are kept compact by the
            # bundle builder, while this exception recovers packages already
            # accepted by production before that preview was bounded.
            exact_evidence = (
                path in {
                    ("chapters", "prompts"),
                    ("chapters", "events", "summary"),
                    ("patch", "text"),
                    ("rendered_markdown",),
                    ("tests", "command"),
                }
                or path[:3] == ("chapters", "events", "data")
            )
            limit = MAX_RAW_BYTES if exact_evidence else MAX_NESTED_STRING_CHARS
            if len(value) > limit: raise ArtifactValidationError("remote artifact string exceeds limit")
        elif isinstance(value, Mapping):
            if len(value) > 1_000: raise ArtifactValidationError("remote artifact mapping exceeds limit")
            for key, nested in value.items():
                if not isinstance(key, str) or len(key) > 256: raise ArtifactValidationError("remote artifact key is invalid")
                bounded(nested, depth + 1, (*path, key))
        elif isinstance(value, list):
            if len(value) > 10_000: raise ArtifactValidationError("remote artifact array exceeds limit")
            for nested in value: bounded(nested, depth + 1, path)
        elif value is not None and not isinstance(value, (bool, int, float)):
            raise ArtifactValidationError("remote artifact value is invalid")
    bounded(content)

    def exact_keys(value: Mapping[str, Any], required: set[str], allowed: set[str], label: str) -> None:
        if not required.issubset(value) or set(value) - allowed:
            raise ArtifactValidationError(f"remote artifact {label} fields are invalid")

    exact_keys(
        content,
        {"schema", "subject", "current", "chapters", "patch", "tests", "provenance", "redactions", "omissions", "rendered_markdown"},
        {"schema", "subject", "current", "chapters", "patch", "tests", "provenance", "redactions", "omissions", "rendered_markdown"},
        "top-level",
    )
    subject = content["subject"]
    if not isinstance(subject, Mapping):
        raise ArtifactValidationError("remote artifact subject is invalid")
    subject_required = {"key", "repository", "pr_number", "base_ref", "base_sha", "merge_base_sha", "head_sha"}
    exact_keys(subject, subject_required, subject_required | {"pr_url"}, "subject")
    if (
        subject.get("key") != subject_key
        or len(subject_key) < 3
        or not isinstance(subject.get("repository"), str)
        or not subject["repository"]
        or isinstance(subject.get("pr_number"), bool)
        or not isinstance(subject.get("pr_number"), int)
        or subject["pr_number"] < 1
        or not isinstance(subject.get("base_ref"), str)
        or any(not _valid_sha(subject.get(field)) for field in ("base_sha", "merge_base_sha", "head_sha"))
        or subject.get("pr_url") is not None and not isinstance(subject.get("pr_url"), str)
    ):
        raise ArtifactValidationError("remote artifact subject is invalid")
    current = content["current"]
    if not isinstance(current, Mapping):
        raise ArtifactValidationError("remote artifact current state is invalid")
    exact_keys(current, {"complete", "capture_mode", "capture_fidelity", "generated_at"}, {"complete", "capture_mode", "capture_fidelity", "generated_at"}, "current")
    if (
        not isinstance(current["complete"], bool)
        or current["capture_mode"] not in {"review_capsule", "metadata_only", "local_review"}
        or current["capture_fidelity"] not in {"exact", "partial", "self_reported"}
        or not isinstance(current["generated_at"], str)
    ):
        raise ArtifactValidationError("remote artifact current state is invalid")
    chapters = content["chapters"]
    if not isinstance(chapters, list) or not chapters or len(chapters) > 10_000:
        raise ArtifactValidationError("remote artifact chapters are invalid")
    ids = set()
    for chapter in chapters:
        if not isinstance(chapter, Mapping):
            raise ArtifactValidationError("remote artifact chapter is invalid")
        required = {"session_id", "capture_fidelity", "prompts", "events", "execution_spans"}
        if (
            not required.issubset(chapter)
            or not isinstance(chapter.get("session_id"), str)
            or len(chapter["session_id"]) < 8
            or len(chapter["session_id"]) > 128
            or chapter.get("capture_fidelity") not in {"exact", "partial", "self_reported"}
        ):
            raise ArtifactValidationError("remote artifact session identity is invalid")
        for field in ("prompts", "events", "execution_spans"):
            if not isinstance(chapter[field], list):
                raise ArtifactValidationError("remote artifact chapter collection is invalid")
        if any(not isinstance(prompt, str) for prompt in chapter["prompts"]):
            raise ArtifactValidationError("remote artifact prompt is invalid")
        for event in chapter["events"]:
            if (
                not isinstance(event, Mapping)
                or not {"event_id", "sequence", "type", "summary", "data"}.issubset(event)
                or not isinstance(event["event_id"], str)
                or isinstance(event["sequence"], bool)
                or not isinstance(event["sequence"], int)
                or event["sequence"] < 1
                or event["type"] not in {"human_prompt", "agent_message", "tool_action", "tool_result", "decision", "git", "test"}
                or not isinstance(event["summary"], str)
                or not isinstance(event["data"], Mapping)
            ):
                raise ArtifactValidationError("remote artifact event is invalid")
        for span in chapter["execution_spans"]:
            if (
                not isinstance(span, Mapping)
                or not {"id", "harness", "model"}.issubset(span)
                or not isinstance(span["id"], str)
                or span.get("parent_id") is not None and not isinstance(span.get("parent_id"), str)
            ):
                raise ArtifactValidationError("remote artifact span is invalid")
            for field in ("harness", "model"):
                _validate_provenance(span[field])
        if chapter["session_id"] in ids:
            raise ArtifactValidationError("remote artifact has duplicate session chapters")
        ids.add(chapter["session_id"])

    patch = content["patch"]
    if not isinstance(patch, Mapping) or not {"text", "stats"}.issubset(patch) or not isinstance(patch["text"], str) or not isinstance(patch["stats"], Mapping):
        raise ArtifactValidationError("remote artifact patch is invalid")
    stats = patch["stats"]
    if not {"files", "added", "deleted"}.issubset(stats) or any(isinstance(stats[field], bool) or not isinstance(stats[field], int) or stats[field] < 0 for field in ("files", "added", "deleted")):
        raise ArtifactValidationError("remote artifact patch stats are invalid")
    tests = content["tests"]
    if not isinstance(tests, list):
        raise ArtifactValidationError("remote artifact tests are invalid")
    for test in tests:
        if not isinstance(test, Mapping) or not {"command", "outcome"}.issubset(test) or not isinstance(test["command"], str) or test["outcome"] not in {"passed", "failed", "unknown", "attempted"}:
            raise ArtifactValidationError("remote artifact test is invalid")
    provenance = content["provenance"]
    if not isinstance(provenance, Mapping):
        raise ArtifactValidationError("remote artifact provenance is invalid")
    for value in provenance.values():
        _validate_provenance(value)
    redactions = content["redactions"]
    omissions = content["omissions"]
    if not isinstance(redactions, list) or not isinstance(omissions, list) or not isinstance(content["rendered_markdown"], str):
        raise ArtifactValidationError("remote artifact summary fields are invalid")
    for redaction in redactions:
        if not isinstance(redaction, Mapping):
            raise ArtifactValidationError("remote artifact redaction is invalid")
        exact_keys(redaction, {"category", "count"}, {"category", "count"}, "redaction")
        if not isinstance(redaction["category"], str) or not redaction["category"] or isinstance(redaction["count"], bool) or not isinstance(redaction["count"], int) or redaction["count"] < 1:
            raise ArtifactValidationError("remote artifact redaction is invalid")
    for omission in omissions:
        if not isinstance(omission, Mapping):
            raise ArtifactValidationError("remote artifact omission is invalid")
        exact_keys(omission, {"category", "reason"}, {"category", "reason"}, "omission")
        if not isinstance(omission["category"], str) or not omission["category"] or not isinstance(omission["reason"], str) or not omission["reason"]:
            raise ArtifactValidationError("remote artifact omission is invalid")
    return json.loads(raw)


def _validate_provenance(value: object) -> None:
    if (
        not isinstance(value, Mapping)
        or not {"value", "source"}.issubset(value)
        or value["value"] is not None and not isinstance(value["value"], str)
        or value["source"] not in {"observed", "harness_reported", "agent_reported", "unknown"}
    ):
        raise ArtifactValidationError("remote artifact provenance value is invalid")

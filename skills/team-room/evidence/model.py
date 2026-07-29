"""Immutable normalized data used by the local evidence pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
import re
from typing import Any, Mapping

EVENT_TYPES = frozenset({"human_prompt", "agent_message", "tool_action", "tool_result", "decision", "git", "test"})
PROVENANCE_SOURCES = frozenset({"observed", "harness_reported", "agent_reported", "unknown"})
CAPTURE_FIDELITIES = frozenset({"exact", "partial", "self_reported"})


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list) or isinstance(value, tuple):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("evidence JSON cannot contain non-finite floats")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"evidence values must be JSON values, got {type(value).__name__}")


def thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class ProvenanceValue:
    value: str | None
    source: str = "unknown"

    def __post_init__(self) -> None:
        if self.value is not None and not isinstance(self.value, str):
            raise ValueError("provenance values must be strings or null")
        if self.source not in PROVENANCE_SOURCES:
            raise ValueError(f"unsupported provenance source: {self.source}")
        if self.source == "unknown" and self.value is not None:
            raise ValueError("unknown provenance must not invent a value")

    def json(self) -> dict[str, str | None]:
        return {"value": self.value, "source": self.source}


UNKNOWN = ProvenanceValue(None, "unknown")


@dataclass(frozen=True)
class Subject:
    repository: str
    pr_number: int
    pr_url: str | None
    base_ref: str
    base_sha: str
    merge_base_sha: str
    head_sha: str

    def __post_init__(self) -> None:
        if not self.repository or self.pr_number <= 0:
            raise ValueError("subject needs a repository and positive PR number")
        if not all(re.fullmatch(r"[0-9a-f]{40,64}", sha) for sha in (self.base_sha, self.merge_base_sha, self.head_sha)):
            raise ValueError("subject needs full lowercase hexadecimal base, merge-base, and head SHAs")

    @property
    def key(self) -> str:
        return f"{self.repository}#{self.pr_number}"

    def json(self) -> dict[str, Any]:
        return {"key": self.key, "repository": self.repository, "pr_number": self.pr_number,
                "pr_url": self.pr_url, "base_ref": self.base_ref, "base_sha": self.base_sha,
                "merge_base_sha": self.merge_base_sha, "head_sha": self.head_sha}


@dataclass(frozen=True)
class EvidenceEvent:
    id: str
    sequence: int
    type: str
    summary: str
    data: Mapping[str, Any] = field(default_factory=dict)
    execution_span_id: str | None = None
    occurred_at: str | None = None

    def __post_init__(self) -> None:
        if not self.id or self.sequence < 1 or self.type not in EVENT_TYPES:
            raise ValueError("event id, positive sequence, and declared type are required")
        object.__setattr__(self, "data", _freeze(self.data))

    def json(self) -> dict[str, Any]:
        return {"event_id": self.id, "sequence": self.sequence, "type": self.type,
                "summary": self.summary, "data": thaw(self.data),
                "execution_span_id": self.execution_span_id, "occurred_at": self.occurred_at}


@dataclass(frozen=True)
class ExecutionSpan:
    id: str
    parent_id: str | None = None
    harness: ProvenanceValue = UNKNOWN
    model: ProvenanceValue = UNKNOWN
    reasoning_effort: ProvenanceValue = UNKNOWN
    agent_type: ProvenanceValue = UNKNOWN
    execution_mode: ProvenanceValue = UNKNOWN

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("execution span requires an ID")

    def json(self) -> dict[str, Any]:
        return {"id": self.id, "parent_id": self.parent_id, "harness": self.harness.json(),
                "model": self.model.json(), "reasoning_effort": self.reasoning_effort.json(),
                "agent_type": self.agent_type.json(), "execution_mode": self.execution_mode.json()}


@dataclass(frozen=True)
class Chapter:
    session_id: str
    events: tuple[EvidenceEvent, ...]
    execution_spans: tuple[ExecutionSpan, ...] = ()
    capture_fidelity: str = "exact"

    def __post_init__(self) -> None:
        if not self.session_id or self.capture_fidelity not in CAPTURE_FIDELITIES:
            raise ValueError("chapter needs a stable session ID and declared fidelity")
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "execution_spans", tuple(self.execution_spans))
        sequences = [event.sequence for event in self.events]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("chapter event sequences must increase monotonically")
        span_ids = {span.id for span in self.execution_spans}
        if any(span.parent_id is not None and span.parent_id not in span_ids for span in self.execution_spans):
            raise ValueError("execution span parents must be declared in the chapter")
        if any(event.execution_span_id is not None and event.execution_span_id not in span_ids for event in self.events):
            raise ValueError("event execution spans must be declared in the chapter")

    @classmethod
    def from_events(cls, session_id: str, events: list[EvidenceEvent] | tuple[EvidenceEvent, ...],
                    spans: list[ExecutionSpan] | tuple[ExecutionSpan, ...], capture_fidelity: str = "exact") -> "Chapter":
        return cls(session_id, tuple(events), tuple(spans), capture_fidelity)

    def json(self) -> dict[str, Any]:
        events = [event.json() for event in self.events]
        return {"session_id": self.session_id, "capture_fidelity": self.capture_fidelity,
                "prompts": [event.summary for event in self.events if event.type == "human_prompt"],
                "events": events, "execution_spans": [span.json() for span in self.execution_spans]}


@dataclass(frozen=True)
class Patch:
    text: str
    files: int
    added: int
    deleted: int

    def __post_init__(self) -> None:
        if min(self.files, self.added, self.deleted) < 0:
            raise ValueError("patch statistics must be nonnegative")

    def json(self) -> dict[str, Any]:
        return {"text": self.text, "stats": {"files": self.files, "added": self.added, "deleted": self.deleted}}


@dataclass(frozen=True)
class TestEvidence:
    command: str
    outcome: str

    def __post_init__(self) -> None:
        if self.outcome not in {"passed", "failed", "unknown", "attempted"}:
            raise ValueError("test outcome must be declared")

    def json(self) -> dict[str, str]:
        return {"command": self.command, "outcome": self.outcome}


@dataclass(frozen=True)
class Redaction:
    category: str
    count: int = 1

    def __post_init__(self) -> None:
        if not self.category or self.count < 1:
            raise ValueError("redaction requires category and positive count")


@dataclass(frozen=True)
class Omission:
    category: str
    reason: str


@dataclass(frozen=True)
class Detection:
    harness: str
    session_id: str
    root: str


@dataclass(frozen=True)
class SessionSource:
    harness: str
    session_id: str
    path: str | None = None
    command: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.harness or not self.session_id or (self.path is not None and not isinstance(self.path, str)):
            raise ValueError("session source fields are invalid")
        object.__setattr__(self, "command", tuple(self.command))
        if any(not isinstance(part, str) for part in self.command):
            raise ValueError("session commands must be immutable strings")


@dataclass(frozen=True)
class BundleResult:
    path: str
    sha256: str
    size: int
    complete: bool
    omissions: tuple[Omission, ...]
    rendered_markdown: str
    next_checkpoint: Any

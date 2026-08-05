"""Shared exact-file transcript mechanics for adapter implementations."""
from __future__ import annotations

from abc import ABC, abstractmethod
import json
import hashlib
from pathlib import Path
from typing import Iterator, Mapping

from ..checkpoint import Checkpoint, checkpoint_for, valid_for
from ..model import Chapter, Detection, EvidenceEvent, ExecutionSpan, SessionSource


class Adapter(ABC):
    capture_fidelity = "exact"
    MAX_RECORD_BYTES = 1_048_576
    # Real transcripts routinely carry single records past MAX_RECORD_BYTES
    # (a pasted image, a huge tool result). Hard-failing at 1MB silently
    # killed six publishes on one machine in five days — the biggest
    # sessions, exactly the trajectories worth keeping. Records up to this
    # ceiling are read whole and flow into the bundler's sanitize/degrade
    # tiers, which bound what actually ships; only a pathological line
    # (runaway writer, corrupt file) still aborts.
    HARD_RECORD_CEILING = 32 * 1_048_576
    @abstractmethod
    def detect(self, env: Mapping[str, str], cwd: Path) -> Detection | None: ...

    @abstractmethod
    def resolve_session(self, detection: Detection, explicit_id: str | None) -> SessionSource: ...

    @abstractmethod
    def _event_from_record(self, record: dict, sequence: int, source: SessionSource) -> EvidenceEvent | None: ...

    def _events_from_record(self, record: dict, sequence: int, source: SessionSource) -> list[EvidenceEvent]:
        event = self._event_from_record(record, sequence, source)
        return [event] if event is not None else []

    def _event_from_json(self, value: str) -> EvidenceEvent:
        raw = json.loads(value)
        return EvidenceEvent(raw["event_id"], raw["sequence"], raw["type"], raw["summary"], raw.get("data", {}), raw.get("execution_span_id"), raw.get("occurred_at"))

    def _records(self, source: SessionSource, checkpoint: Checkpoint | None) -> tuple[list[EvidenceEvent], Checkpoint]:
        if not source.path:
            raise ValueError("file adapter needs a transcript path")
        path = Path(source.path)
        # Checkpoints never contain event bodies: even sanitized spool state is
        # needless risk here. Rebuild the complete chapter from this bounded
        # snapshot so append resumes cannot omit historical evidence.
        start = 0
        events: list[EvidenceEvent] = []
        sequence = 0
        # Snapshot once before opening. Bytes appended after this point are not
        # silently claimed by this checkpoint; they appear on the next pass.
        snapshot_stat = path.stat()
        snapshot_size = snapshot_stat.st_size
        full_offset = start
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            # Hash the retained prefix in bounded chunks from this same open file.
            remaining = start
            while remaining:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                remaining -= len(chunk)
            handle.seek(start)
            while handle.tell() < snapshot_size:
                before = handle.tell()
                line = handle.readline(self.MAX_RECORD_BYTES + 1)
                if not line:
                    break
                if len(line) > self.MAX_RECORD_BYTES and not line.endswith(b"\n"):
                    # Oversized record: keep reading it under the hard ceiling
                    # instead of failing the whole publish.
                    chunks = [line]
                    total = len(line)
                    while not chunks[-1].endswith(b"\n"):
                        more = handle.readline(self.HARD_RECORD_CEILING + 1)
                        if not more:
                            break
                        total += len(more)
                        if total > self.HARD_RECORD_CEILING:
                            raise ValueError(
                                f"transcript JSONL record exceeds {self.HARD_RECORD_CEILING} byte hard ceiling"
                            )
                        chunks.append(more)
                    line = b"".join(chunks)
                if not line.endswith(b"\n"):
                    break  # a writer may still be appending this JSONL record
                try:
                    raw = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"invalid transcript JSONL in {path}: {exc}") from exc
                if isinstance(raw, dict):
                    for candidate in self._events_from_record(raw, sequence + 1, source):
                        sequence = candidate.sequence
                        events.append(candidate)
                digest.update(line)
                full_offset = handle.tell()
        checkpoint = Checkpoint(snapshot_stat.st_dev, snapshot_stat.st_ino, full_offset, digest.hexdigest(), sequence, ())
        return events, checkpoint

    def read_events(self, source: SessionSource, checkpoint: Checkpoint | None) -> tuple[list[EvidenceEvent], Checkpoint]:
        events, next_checkpoint = self._records(source, checkpoint)
        return events, next_checkpoint

    def iter_events(self, source: SessionSource, checkpoint: Checkpoint | None) -> Iterator[EvidenceEvent]:
        yield from self.read_events(source, checkpoint)[0]

    def execution_spans(self, source: SessionSource) -> list[ExecutionSpan]:
        return []

    def chapter(self, source: SessionSource, checkpoint: Checkpoint | None = None) -> tuple[Chapter, Checkpoint | None]:
        events, next_checkpoint = self.read_events(source, checkpoint)
        return Chapter.from_events(source.session_id, events, self.execution_spans(source), self.capture_fidelity), next_checkpoint

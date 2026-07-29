"""Bounded adapter for a customer-supplied JSONL evidence producer."""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess
import time
from typing import Iterator, Mapping

from .base import Adapter
from ..model import Detection, EvidenceEvent, ExecutionSpan, ProvenanceValue, SessionSource


class GenericAdapter(Adapter):
    name = "generic"
    capture_fidelity = "self_reported"

    def __init__(self, command: list[str], deadline_seconds: float = 5.0, stdout_limit: int = 1_048_576, stderr_limit: int = 65_536):
        self.command = tuple(command)
        self.deadline_seconds = deadline_seconds
        self.stdout_limit = stdout_limit
        self.stderr_limit = stderr_limit

    def detect(self, env: Mapping[str, str], cwd: Path) -> Detection | None:
        return Detection(self.name, "", str(cwd)) if self.command else None

    def resolve_session(self, detection: Detection, explicit_id: str | None) -> SessionSource:
        if not explicit_id:
            raise ValueError("generic evidence requires an explicit stable session ID")
        return SessionSource(self.name, explicit_id, command=self.command)

    def _event_from_record(self, record: dict, sequence: int, source: SessionSource) -> EvidenceEvent | None:
        kind = record.get("type")
        if kind not in {"human_prompt", "agent_message", "tool_action", "tool_result", "decision", "git", "test"}:
            return None
        declared = record.get("sequence")
        if not isinstance(declared, int) or declared != sequence:
            raise ValueError("generic producer event sequences must increase exactly")
        if record.get("session_id") != source.session_id:
            raise ValueError("generic producer session ID does not match the requested session")
        return EvidenceEvent(f"{source.session_id}:{sequence}", sequence, kind, str(record.get("summary", "")), record.get("data", {}), source.session_id)

    def _run(self, source: SessionSource) -> tuple[bytes, bytes]:
        env = {"ROOM_EVIDENCE_SESSION_ID": source.session_id, "PATH": os.defpath, "LANG": "C"}
        process = subprocess.Popen(source.command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        assert process.stdout and process.stderr
        output = {process.stdout: bytearray(), process.stderr: bytearray()}
        limits = {process.stdout: self.stdout_limit, process.stderr: self.stderr_limit}
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        selector.register(process.stderr, selectors.EVENT_READ)
        deadline = time.monotonic() + self.deadline_seconds
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("generic evidence producer exceeded cumulative deadline")
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output[key.fileobj].extend(chunk)
                    if len(output[key.fileobj]) > limits[key.fileobj]:
                        raise ValueError("generic evidence producer exceeded stdout/stderr byte cap")
            if process.wait(timeout=max(0.0, deadline - time.monotonic())) != 0:
                raise ValueError("generic evidence producer failed: " + bytes(output[process.stderr]).decode("utf-8", "replace")[:512])
            return bytes(output[process.stdout]), bytes(output[process.stderr])
        except Exception:
            process.kill()
            process.wait()
            raise
        finally:
            selector.close()

    def read_events(self, source: SessionSource, checkpoint) -> tuple[list[EvidenceEvent], None]:
        stdout, _ = self._run(source)
        events: list[EvidenceEvent] = []
        for line in stdout.splitlines():
            raw = json.loads(line.decode("utf-8"))
            event = self._event_from_record(raw, len(events) + 1, source)
            if event:
                events.append(event)
        return events, None

    def iter_events(self, source: SessionSource, checkpoint) -> Iterator[EvidenceEvent]:
        yield from self.read_events(source, checkpoint)[0]

    def execution_spans(self, source: SessionSource) -> list[ExecutionSpan]:
        return [ExecutionSpan(source.session_id, harness=ProvenanceValue("generic", "agent_reported"))]

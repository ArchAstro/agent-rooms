"""Native adapters for private first-party harness capture files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .base import Adapter
from ..model import (
    Detection,
    EvidenceEvent,
    ExecutionSpan,
    ProvenanceValue,
    SessionSource,
)


class FirstPartyAdapter(Adapter):
    capture_fidelity = "partial"
    SUPPORTED = {"astrodev", "issue-fixer"}

    def __init__(self, harness: str, capture: bytes):
        if harness not in self.SUPPORTED:
            raise ValueError("unsupported first-party evidence harness")
        self.name = harness
        self.records = []
        for line in capture.splitlines():
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("first-party evidence capture is invalid JSONL") from exc
            if not isinstance(record, dict):
                raise ValueError("first-party evidence capture records must be objects")
            self.records.append(record)

    def detect(self, env: Mapping[str, str], cwd: Path) -> Detection | None:
        return Detection(self.name, "", str(cwd))

    def resolve_session(
        self, detection: Detection, explicit_id: str | None
    ) -> SessionSource:
        if not explicit_id:
            raise ValueError("first-party evidence requires a stable session ID")
        if self._declared_session() != explicit_id:
            raise ValueError("first-party capture session does not match handoff")
        return SessionSource(self.name, explicit_id)

    def _declared_session(self) -> str | None:
        for record in self.records:
            if self.name == "astrodev" and record.get("type") == "session":
                return record.get("id") if isinstance(record.get("id"), str) else None
            if (
                self.name == "issue-fixer"
                and record.get("type") == "issue_fixer_session"
            ):
                value = record.get("session_id")
                return value if isinstance(value, str) else None
        return None

    def _event_from_record(
        self, record: dict, sequence: int, source: SessionSource
    ) -> EvidenceEvent | None:
        return None

    def read_events(self, source: SessionSource, checkpoint):
        events = (
            self._astrodev_events(source)
            if self.name == "astrodev"
            else self._issue_fixer_events(source)
        )
        return events, None

    def _astrodev_events(self, source: SessionSource) -> list[EvidenceEvent]:
        events = []
        for record in self.records:
            kind = record.get("type")
            timestamp = record.get("timestamp")
            if kind == "message":
                message = record.get("message")
                if not isinstance(message, dict):
                    continue
                role = message.get("role")
                content = message.get("content")
                if role not in {"user", "assistant"} or not isinstance(content, list):
                    continue
                text = "".join(
                    part["text"]
                    for part in content
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                )
                if text:
                    events.append(
                        self._event(
                            source,
                            len(events) + 1,
                            "human_prompt" if role == "user" else "agent_message",
                            text,
                            {},
                            timestamp,
                        )
                    )
            elif kind == "thinking" and isinstance(record.get("content"), str):
                events.append(
                    self._event(
                        source,
                        len(events) + 1,
                        "decision",
                        record["content"],
                        {},
                        timestamp,
                    )
                )
            elif kind == "tool_result" and isinstance(record.get("content"), str):
                events.append(
                    self._event(
                        source,
                        len(events) + 1,
                        "tool_result",
                        record["content"],
                        {
                            "tool": record.get("name"),
                            "input": record.get("input"),
                        },
                        timestamp,
                    )
                )
            elif kind == "command" and isinstance(record.get("command"), str):
                events.append(
                    self._event(
                        source,
                        len(events) + 1,
                        "tool_action",
                        "command",
                        {"command": record["command"]},
                        timestamp,
                    )
                )
            elif kind == "capture_omission":
                events.append(
                    self._event(
                        source,
                        len(events) + 1,
                        "decision",
                        str(
                            record.get("reason")
                            or "trajectory omitted from bounded capture"
                        ),
                        {
                            "omitted_bytes": record.get("omitted_bytes"),
                            "omitted_events": record.get("omitted_events"),
                        },
                        timestamp,
                    )
                )
        return events

    def _issue_fixer_events(self, source: SessionSource) -> list[EvidenceEvent]:
        events = []
        current_thread = source.session_id
        for record in self.records:
            kind = record.get("type")
            if kind == "issue_fixer_prompt" and isinstance(
                record.get("content"), str
            ):
                current_thread = source.session_id
                events.append(
                    self._event(
                        source,
                        len(events) + 1,
                        "human_prompt",
                        record["content"],
                        {"round": record.get("round")},
                        None,
                        current_thread,
                    )
                )
                continue
            if kind == "capture_omission":
                events.append(
                    self._event(
                        source,
                        len(events) + 1,
                        "decision",
                        str(
                            record.get("reason")
                            or "trajectory omitted from bounded capture"
                        ),
                        {
                            "round": record.get("round"),
                            "omitted_events": record.get("omitted_events"),
                            "omitted_bytes": record.get("omitted_bytes"),
                        },
                        None,
                        source.session_id,
                    )
                )
                continue
            if kind != "codex_event" or not isinstance(record.get("event"), dict):
                continue
            raw = record["event"]
            if raw.get("type") == "thread.started" and isinstance(
                raw.get("thread_id"), str
            ):
                current_thread = raw["thread_id"]
                continue
            if raw.get("type") != "item.completed":
                continue
            item = raw.get("item")
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "agent_message" and isinstance(item.get("text"), str):
                events.append(
                    self._event(
                        source,
                        len(events) + 1,
                        "agent_message",
                        item["text"],
                        {"round": record.get("round")},
                        None,
                        current_thread,
                    )
                )
            elif item_type == "command_execution" and isinstance(
                item.get("command"), str
            ):
                events.append(
                    self._event(
                        source,
                        len(events) + 1,
                        "tool_action",
                        "command_execution",
                        {
                            "command": item["command"],
                            "round": record.get("round"),
                        },
                        None,
                        current_thread,
                    )
                )
                output = item.get("aggregated_output")
                if isinstance(output, str):
                    events.append(
                        self._event(
                            source,
                            len(events) + 1,
                            "tool_result",
                            output,
                            {
                                "exit_code": item.get("exit_code"),
                                "round": record.get("round"),
                            },
                            None,
                            current_thread,
                        )
                    )
        return events

    def _event(
        self,
        source,
        sequence,
        kind,
        summary,
        data,
        occurred_at,
        span_id=None,
    ):
        return EvidenceEvent(
            f"{source.session_id}:{sequence}",
            sequence,
            kind,
            summary,
            data,
            span_id or source.session_id,
            occurred_at if isinstance(occurred_at, str) else None,
        )

    def execution_spans(self, source: SessionSource) -> list[ExecutionSpan]:
        spans = [
            ExecutionSpan(
                source.session_id,
                harness=ProvenanceValue(self.name, "observed"),
            )
        ]
        if self.name == "issue-fixer":
            seen = {source.session_id}
            for record in self.records:
                raw = record.get("event")
                thread = raw.get("thread_id") if isinstance(raw, dict) else None
                if (
                    isinstance(thread, str)
                    and raw.get("type") == "thread.started"
                    and thread not in seen
                ):
                    seen.add(thread)
                    spans.append(
                        ExecutionSpan(
                            thread,
                            source.session_id,
                            harness=ProvenanceValue("codex", "observed"),
                        )
                    )
        return spans

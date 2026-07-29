"""Exact-session adapter for visible Claude JSONL transcript records."""
from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Mapping

from .base import Adapter
from ..model import Detection, EvidenceEvent, ExecutionSpan, ProvenanceValue, SessionSource


class ClaudeAdapter(Adapter):
    name = "claude"

    def detect(self, env: Mapping[str, str], cwd: Path) -> Detection | None:
        session_id = env.get("CLAUDE_SESSION_ID", "").strip()
        if not session_id:
            return None
        root = Path(env.get("CLAUDE_HOME", str(Path(env.get("HOME", "")) / ".claude")))
        return Detection(self.name, session_id, str(root))

    def resolve_session(self, detection: Detection, explicit_id: str | None) -> SessionSource:
        if explicit_id and detection.session_id and explicit_id != detection.session_id:
            raise ValueError("explicit Claude session conflicts with native session identity")
        session_id = explicit_id or detection.session_id
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}", session_id):
            raise ValueError("invalid Claude session ID")
        root = Path(detection.root) / "projects"
        direct = root / f"{session_id}.jsonl"
        matches = [direct] if direct.is_file() else list(root.glob(f"**/{session_id}.jsonl"))
        matches = [path for path in matches if path.resolve().is_relative_to(root.resolve())]
        if len(matches) != 1:
            raise ValueError(f"exact Claude session {session_id!r} was not found uniquely")
        with matches[0].open(encoding="utf-8") as handle:
            saw_authoritative_id = False
            for line in handle:
                record = json.loads(line)
                actual = record.get("sessionId")
                if actual is not None:
                    saw_authoritative_id = True
                    if actual != session_id:
                        raise ValueError("Claude transcript metadata does not match the requested session")
        if not saw_authoritative_id:
            raise ValueError("Claude transcript metadata has no authoritative sessionId")
        return SessionSource(self.name, session_id, str(matches[0]))

    def _event_from_record(self, record: dict, sequence: int, source: SessionSource) -> EvidenceEvent | None:
        events = self._events_from_record(record, sequence, source)
        return events[0] if events else None

    def _events_from_record(self, record: dict, sequence: int, source: SessionSource) -> list[EvidenceEvent]:
        role = record.get("type")
        if role == "user" and record.get("isMeta") is True:
            return []
        if role not in {"user", "assistant"}:
            return []
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        if isinstance(content, str):
            return [EvidenceEvent(f"{source.session_id}:{sequence}", sequence, "human_prompt" if role == "user" else "agent_message", content, {}, source.session_id, record.get("timestamp"))]
        if not isinstance(content, list):
            return []
        events = []
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str):
                events.append(EvidenceEvent(f"{source.session_id}:{sequence + len(events)}", sequence + len(events), "human_prompt" if role == "user" else "agent_message", block["text"], {}, source.session_id, record.get("timestamp")))
            if kind == "tool_use" and role == "assistant":
                events.append(EvidenceEvent(f"{source.session_id}:{sequence + len(events)}", sequence + len(events), "tool_action", str(block.get("name", "tool")), {"command": block.get("input", {}), "call_id": block.get("id")}, source.session_id, record.get("timestamp")))
            if kind == "tool_result" and role == "user":
                text = block.get("content", "")
                if isinstance(text, list): text = "\n".join(str(item.get("text", "")) for item in text if isinstance(item, dict))
                exit_match = re.search(r"exit code:\s*(\d+)", str(text), re.I)
                data = {"call_id": block.get("tool_use_id")}
                if exit_match: data["exit_code"] = int(exit_match.group(1))
                events.append(EvidenceEvent(f"{source.session_id}:{sequence + len(events)}", sequence + len(events), "tool_result", str(text), data, source.session_id, record.get("timestamp")))
        return events

    def execution_spans(self, source: SessionSource) -> list[ExecutionSpan]:
        return [ExecutionSpan(source.session_id, harness=ProvenanceValue("claude", "observed"))]

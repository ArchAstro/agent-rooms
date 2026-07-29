"""Exact-session adapter for visible Codex JSONL transcript records."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping

from .base import Adapter
from ..model import Detection, EvidenceEvent, ExecutionSpan, ProvenanceValue, SessionSource, UNKNOWN


class CodexAdapter(Adapter):
    name = "codex"

    def detect(self, env: Mapping[str, str], cwd: Path) -> Detection | None:
        session_id = env.get("CODEX_THREAD_ID", "").strip()
        if not session_id:
            return None
        root = Path(env.get("CODEX_HOME", str(Path(env.get("HOME", "")) / ".codex")))
        return Detection(self.name, session_id, str(root))

    def resolve_session(self, detection: Detection, explicit_id: str | None) -> SessionSource:
        session_id = explicit_id or detection.session_id
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}", session_id):
            raise ValueError("invalid Codex session ID")
        root = Path(detection.root) / "sessions"
        resolved_root = root.resolve()
        matches = list(root.glob(f"**/rollout-*-{session_id}.jsonl")) + list(root.glob(f"**/{session_id}.jsonl"))
        matches = [path for path in matches if path.resolve().is_relative_to(resolved_root)]
        if len(matches) != 1:
            raise ValueError(f"exact Codex session {session_id!r} was not found uniquely")
        with matches[0].open(encoding="utf-8") as handle:
            first = json.loads(handle.readline())
        internal = first.get("payload", {}).get("id") if isinstance(first.get("payload"), dict) else None
        if internal != session_id:
            raise ValueError("Codex transcript metadata does not match the requested session")
        return SessionSource(self.name, session_id, str(matches[0]))

    def _event_from_record(self, record: dict, sequence: int, source: SessionSource) -> EvidenceEvent | None:
        if record.get("type") != "response_item":
            return None
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return None
        kind = payload.get("type")
        span_id = record.get("span_id") or source.session_id
        if kind == "message":
            role = payload.get("role")
            if role not in {"user", "assistant"}:
                return None
            parts = payload.get("content", [])
            text = "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str))
            if not text:
                return None
            return EvidenceEvent(f"{source.session_id}:{sequence}", sequence, "human_prompt" if role == "user" else "agent_message", text, {}, span_id, record.get("timestamp"))
        if kind in {"function_call", "custom_tool_call", "tool_search_call", "web_search_call"}:
            name = str(payload.get("name", "tool"))
            command = str(payload.get("arguments", payload.get("input", payload.get("query", ""))))
            return EvidenceEvent(f"{source.session_id}:{sequence}", sequence, "tool_action", name, {"command": command, "call_id": payload.get("call_id")}, span_id, record.get("timestamp"))
        if kind in {"function_call_output", "custom_tool_call_output", "tool_search_output", "web_search_output"}:
            output = str(payload.get("output", ""))
            # The summary is the bounded shareable excerpt; retaining the same
            # raw output again in data would duplicate both noise and secrets.
            exit_match = re.search(r"exit code:\s*(\d+)", output, re.I)
            data = {"call_id": payload.get("call_id")}
            if exit_match:
                data["exit_code"] = int(exit_match.group(1))
            return EvidenceEvent(f"{source.session_id}:{sequence}", sequence, "tool_result", output, data, span_id, record.get("timestamp"))
        return None

    def execution_spans(self, source: SessionSource) -> list[ExecutionSpan]:
        spans: dict[str, ExecutionSpan] = {source.session_id: ExecutionSpan(source.session_id, harness=ProvenanceValue("codex", "observed"))}
        with Path(source.path or "").open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "turn_context":
                    context = record.get("payload", {}) if isinstance(record.get("payload"), dict) else {}
                    model = context.get("model")
                    effort = context.get("effort", context.get("reasoning_effort"))
                    spans[source.session_id] = ExecutionSpan(source.session_id, harness=ProvenanceValue("codex", "observed"),
                        model=ProvenanceValue(model, "harness_reported") if isinstance(model, str) else UNKNOWN,
                        reasoning_effort=ProvenanceValue(effort, "harness_reported") if isinstance(effort, str) else UNKNOWN)
                if record.get("type") == "subagent_started" and isinstance(record.get("id"), str):
                    child = record["id"]
                    parent = record.get("parent_id") if isinstance(record.get("parent_id"), str) else source.session_id
                    spans[child] = ExecutionSpan(child, parent, harness=ProvenanceValue("codex", "observed"))
        return list(spans.values())

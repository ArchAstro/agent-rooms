"""Streaming-ish, bounded construction of the current local JSON artifact."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time
import re
import shlex
from typing import Any, Iterable, Mapping

from .checkpoint import Checkpoint
from .git_pr import no_lazy_fetch_env
from .model import BundleResult, Chapter, Omission, Patch, Redaction, Subject, TestEvidence, PROVENANCE_SOURCES
from .sanitize import SanitizationError, sanitize, sanitize_event

SCHEMA = "agent-room-pr-evidence/v1"
DEFAULT_MAX_BYTES = 3 * 1024 * 1024
CAPTURE_MODES = {"review_capsule", "metadata_only", "local_review"}
RENDERED_PREVIEW_MAX_BYTES = 96 * 1024


@dataclass(frozen=True)
class GitEvidence:
    patch: Patch
    base_sha: str
    merge_base_sha: str
    head_sha: str


def _git(cwd: Path, *args: str, maximum_bytes: int = DEFAULT_MAX_BYTES) -> str:
    """Run Git with cumulative deadline and byte caps, never capture unbounded output."""
    process = subprocess.Popen(
        ["git", *args],
        cwd=cwd,
        env=no_lazy_fetch_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout and process.stderr
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    selector.register(process.stderr, selectors.EVENT_READ)
    output = {process.stdout: bytearray(), process.stderr: bytearray()}
    limits = {process.stdout: maximum_bytes, process.stderr: 65_536}
    deadline = time.monotonic() + 20
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"git {' '.join(args)} exceeded its cumulative deadline")
            for key, _ in selector.select(remaining):
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output[key.fileobj].extend(chunk)
                if len(output[key.fileobj]) > limits[key.fileobj]:
                    raise ValueError(f"git {' '.join(args)} exceeded its evidence byte cap")
        if process.wait(timeout=max(0, deadline - time.monotonic())) != 0:
            raise ValueError(f"git {' '.join(args)} failed: {bytes(output[process.stderr]).decode('utf-8', 'replace')[:512]}")
        return bytes(output[process.stdout]).decode("utf-8", "replace")
    except Exception:
        process.kill()
        process.wait()
        raise
    finally:
        selector.close()


def git_evidence_from_repo(cwd: Path, base_sha: str, head_sha: str) -> GitEvidence:
    """Bind an artifact to the declared local commits, never a guessed branch."""
    merge_base = _git(cwd, "merge-base", base_sha, head_sha).strip()
    patch = _git(cwd, "diff", "--binary", "--find-renames", merge_base, head_sha)
    # Git binary hunks are unbounded opaque data. Keep the affected-file marker,
    # never the encoded body.
    if "GIT binary patch\n" in patch:
        before, _, after = patch.partition("GIT binary patch\n")
        next_header = after.find("diff --git ")
        patch = before + "GIT binary patch\n[binary patch omitted]\n" + (after[next_header:] if next_header >= 0 else "")
    numstat = _git(cwd, "diff", "--numstat", merge_base, head_sha)
    files = added = deleted = 0
    for line in numstat.splitlines():
        parts = line.split("\t", 2)
        if len(parts) >= 2:
            files += 1
            added += int(parts[0]) if parts[0].isdigit() else 0
            deleted += int(parts[1]) if parts[1].isdigit() else 0
    return GitEvidence(Patch(patch, files, added, deleted), base_sha, merge_base, head_sha)


def _merge_redactions(items: Iterable[Redaction]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for item in items:
        counts[item.category] += item.count
    return [{"category": category, "count": count} for category, count in sorted(counts.items())]


def _chapter_json(chapter: Chapter, excerpt_limit: int) -> tuple[dict[str, Any], list[Redaction], list[Omission]]:
    safe_events = []
    omissions: list[Omission] = []
    for event in chapter.events:
        bounded, omitted = sanitize_event(event, excerpt_limit)
        safe_events.append(bounded)
        omissions.extend(omitted)
    safe, redactions = sanitize({
        "session_id": chapter.session_id, "capture_fidelity": chapter.capture_fidelity,
        "prompts": [event.summary for event in safe_events if event.type == "human_prompt"],
        "events": [event.json() for event in safe_events],
        "execution_spans": [span.json() for span in chapter.execution_spans],
    })
    return safe, list(redactions), omissions


def _tests(chapters: Iterable[Chapter]) -> list[dict[str, str]]:
    return _tests_json(
        [
            {
                "events": [event.json() for event in chapter.events],
            }
            for chapter in chapters
        ]
    )


def _tests_json(chapters: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for chapter in chapters:
        pending: dict[str, str] = {}
        for event in chapter.get("events", []):
            event_type = event.get("type") if isinstance(event, Mapping) else None
            data = event.get("data") if isinstance(event, Mapping) else None
            if event_type == "test":
                command = data.get("command") if isinstance(data, Mapping) else None
                outcome = data.get("outcome") if isinstance(data, Mapping) else None
                if isinstance(command, str) and isinstance(outcome, str):
                    result.append(TestEvidence(command, outcome).json())
            elif event_type == "tool_action":
                command = data.get("command") if isinstance(data, Mapping) else None
                call_id = data.get("call_id") if isinstance(data, Mapping) else None
                recognized = False
                if isinstance(command, str):
                    try: parts = shlex.split(command)
                    except ValueError: parts = []
                    recognized = bool(
                        len(parts) >= 2 and parts[0] in {"python", "python3"} and re.fullmatch(r"tests/test_[^/]+\.py", parts[1]) or
                        parts and parts[0] == "pytest" or
                        len(parts) >= 3 and parts[:2] in (["python", "-m"], ["python3", "-m"]) and parts[2] == "pytest" or
                        len(parts) >= 2 and parts[:2] == ["mix", "test"] or
                        len(parts) >= 3 and parts[:2] == ["aster", "run"] and any("test" in part for part in parts[2:]) or
                        len(parts) >= 2 and parts[:2] in (["npm", "test"], ["cargo", "test"], ["go", "test"])
                    )
                native = event.get("summary") in {"exec_command", "bash", "shell", "Bash"}
                if recognized and native and isinstance(call_id, str):
                    pending[call_id] = command
            elif event_type == "tool_result":
                call_id = data.get("call_id") if isinstance(data, Mapping) else None
                if isinstance(call_id, str) and call_id in pending:
                    exit_code = data.get("exit_code") if isinstance(data, Mapping) else None
                    outcome = "passed" if exit_code == 0 else "failed" if isinstance(exit_code, int) else "unknown"
                    result.append(TestEvidence(pending.pop(call_id), outcome).json())
        result.extend(TestEvidence(command, "attempted").json() for command in pending.values())
    return result


def _preview_items(
    lines: list[str],
    heading: str,
    items: Iterable[str],
    budget: int,
    full_pointer: str,
) -> None:
    lines.extend(["", heading])
    suffix = f"- … Full {full_pointer}"
    used = 0
    found = False
    for item in items:
        found = True
        available = budget - used - len(suffix.encode("utf-8")) - 1
        item_bytes = item.encode("utf-8")
        if len(item_bytes) + 1 > available:
            if available > 2:
                clipped = item_bytes[: available - len("…".encode("utf-8"))]
                lines.append(clipped.decode("utf-8", "ignore") + "…")
            lines.append(suffix)
            return
        lines.append(item)
        used += len(item_bytes) + 1
    if not found:
        lines.append("- None captured")


def _render(subject: Mapping[str, Any], chapters: list[Mapping[str, Any]], patch: Mapping[str, Any], tests: list[Mapping[str, Any]], omissions: list[Omission]) -> str:
    """Render a useful preview without duplicating the complete JSON evidence."""
    prompt_count = sum(len(chapter["prompts"]) for chapter in chapters)
    event_count = sum(len(chapter["events"]) for chapter in chapters)
    stats = patch.get("stats", {})
    lines = [
        f"## Evidence for {subject['key']}",
        "",
        f"Head: `{subject['head_sha']}`",
        "",
        (
            f"Full structured evidence: {prompt_count} prompt(s), "
            f"{event_count} trajectory event(s), and the exact patch are in this attachment."
        ),
    ]
    _preview_items(
        lines,
        "### Prompts",
        (f"- {prompt}" for chapter in chapters for prompt in chapter["prompts"]),
        16 * 1024,
        "prompts: `chapters[].prompts`",
    )
    _preview_items(
        lines,
        "### Trajectory",
        (
            f"- {event['sequence']}. {event['type']}: {event['summary']}"
            for chapter in chapters
            for event in chapter["events"]
        ),
        40 * 1024,
        "trajectory: `chapters[].events`",
    )
    patch_text = patch.get("text", "")
    patch_budget = 24 * 1024
    patch_bytes = patch_text.encode("utf-8")
    patch_preview = patch_bytes[:patch_budget].decode("utf-8", "ignore").rstrip("\n")
    patch_truncated = len(patch_bytes) > patch_budget
    lines.extend([
        "",
        "### Patch",
        (
            f"{stats.get('files', 0)} file(s), +{stats.get('added', 0)} "
            f"/ -{stats.get('deleted', 0)}"
        ),
        "",
        "```diff",
        patch_preview,
        "```",
    ])
    if patch_truncated:
        lines.append("- … Full patch: `patch.text`")
    _preview_items(
        lines,
        "### Tests",
        (f"- `{test['command']}` — {test['outcome']}" for test in tests),
        8 * 1024,
        "test evidence: `tests`",
    )
    if omissions:
        _preview_items(
            lines,
            "### Omissions",
            (f"- {item.category}: {item.reason}" for item in omissions),
            4 * 1024,
            "omission details: `omissions`",
        )
    rendered = "\n".join(lines) + "\n"
    rendered_bytes = rendered.encode("utf-8")
    if len(rendered_bytes) > RENDERED_PREVIEW_MAX_BYTES:
        suffix = "\n\n… Full evidence remains available in the structured attachment.\n"
        prefix = rendered_bytes[
            : RENDERED_PREVIEW_MAX_BYTES - len(suffix.encode("utf-8"))
        ].decode("utf-8", "ignore")
        return prefix + suffix
    return rendered


def _encode(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validate_payload(payload: Mapping[str, Any]) -> None:
    """Dependency-free runtime gate matching the emitted schema's core invariants."""
    if payload.get("schema") != SCHEMA or payload.get("current", {}).get("capture_mode") not in CAPTURE_MODES:
        raise ValueError("invalid evidence schema or capture mode")
    subject = payload.get("subject")
    if not isinstance(subject, Mapping) or not isinstance(subject.get("pr_number"), int) or not all(isinstance(subject.get(key), str) and re.fullmatch(r"[0-9a-f]{40,64}", subject[key]) for key in ("base_sha", "merge_base_sha", "head_sha")):
        raise ValueError("invalid evidence subject")
    for chapter in payload.get("chapters", []):
        if not isinstance(chapter, Mapping) or chapter.get("capture_fidelity") not in {"exact", "partial", "self_reported"}:
            raise ValueError("invalid evidence chapter")
        for event in chapter.get("events", []):
            if not isinstance(event, Mapping) or event.get("type") not in {"human_prompt", "agent_message", "tool_action", "tool_result", "decision", "git", "test"}:
                raise ValueError("invalid evidence event")
    for test in payload.get("tests", []):
        if test.get("outcome") not in {"passed", "failed", "unknown", "attempted"}:
            raise ValueError("invalid test outcome")
    for value in payload.get("provenance", {}).values():
        if not isinstance(value, Mapping) or value.get("source") not in {"observed", "harness_reported", "agent_reported", "unknown"} or value.get("value") is not None and not isinstance(value.get("value"), str):
            raise ValueError("invalid provenance")
    for redaction in payload.get("redactions", []):
        if not isinstance(redaction.get("category"), str) or not isinstance(redaction.get("count"), int) or redaction["count"] < 1:
            raise ValueError("invalid redaction")
    for omission in payload.get("omissions", []):
        if not isinstance(omission.get("category"), str) or not isinstance(omission.get("reason"), str):
            raise ValueError("invalid omission")


def rebuild_payload(template: Mapping[str, Any], chapters: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Pure canonical current-artifact reduction used after a remote merge.

    It deliberately reuses the bundle renderer and derives every human view
    from the complete chapter set; callers must never carry a stale rendered
    markdown/test/provenance view across an optimistic update.
    """
    payload = json.loads(json.dumps(template))
    payload.setdefault("patch", {"text": "", "stats": {"files": 0, "added": 0, "deleted": 0}})
    payload["patch"].setdefault("text", "")
    payload["patch"].setdefault("stats", {"files": 0, "added": 0, "deleted": 0})
    for chapter in chapters:
        if isinstance(chapter, dict):
            chapter.setdefault("prompts", [])
            chapter.setdefault("events", [])
            chapter.setdefault("execution_spans", [])
    payload["chapters"] = chapters
    tests = _tests_json(chapters)
    prompts = events = spans = False
    for chapter in chapters:
        if not isinstance(chapter, Mapping): raise ValueError("invalid merged chapter")
        sid = chapter.get("session_id")
        if not isinstance(sid, str): raise ValueError("invalid merged session")
        prompts = prompts or bool(chapter.get("prompts"))
        events = events or bool(chapter.get("events"))
        spans = spans or bool(chapter.get("execution_spans"))
    payload["tests"] = tests
    payload["provenance"] = payload.get("provenance", {})
    omissions = [Omission(item["category"], item["reason"]) for item in payload.get("omissions", []) if isinstance(item, Mapping) and isinstance(item.get("category"), str) and isinstance(item.get("reason"), str)]
    payload.setdefault("current", {})["complete"] = bool(prompts and events and spans and payload.get("patch", {}).get("text") and any(test["outcome"] in {"passed", "failed"} for test in tests) and not omissions)
    payload["rendered_markdown"] = _render(payload["subject"], chapters, payload.get("patch", {}), tests, omissions)
    payload, added = sanitize(payload)
    counts = {item["category"]: item["count"] for item in payload.get("redactions", []) if isinstance(item, Mapping) and isinstance(item.get("category"), str) and isinstance(item.get("count"), int)}
    for item in added: counts[item.category] = max(counts.get(item.category, 0), item.count)
    payload["redactions"] = [{"category": key, "count": counts[key]} for key in sorted(counts)]
    return payload


def build_bundle(subject: Subject, chapters: Iterable[Chapter], git_evidence: GitEvidence, policy: Mapping[str, Any]) -> BundleResult:
    """Return one fully self-contained, sanitized current artifact.

    The only persisted output is written through a 0600 temporary file and
    atomically renamed into the caller-provided local artifact directory.
    """
    chapter_list = list(chapters)
    if not chapter_list:
        raise ValueError("a complete artifact needs at least one chapter")
    if (git_evidence.base_sha, git_evidence.merge_base_sha, git_evidence.head_sha) != (subject.base_sha, subject.merge_base_sha, subject.head_sha):
        raise ValueError("Git evidence base, merge base, or head does not match the declared subject")
    excerpt_limit = int(policy.get("tool_excerpt_limit", 8192))
    capture_mode = str(policy.get("capture_mode", "review_capsule"))
    if capture_mode not in CAPTURE_MODES:
        raise ValueError("capture mode must be a declared enum")
    all_redactions: list[Redaction] = []
    omissions: list[Omission] = []
    rendered_chapters: list[dict[str, Any]] = []
    for chapter in chapter_list:
        safe, redactions, chapter_omissions = _chapter_json(chapter, excerpt_limit)
        rendered_chapters.append(safe)
        all_redactions.extend(redactions)
        omissions.extend(chapter_omissions)
    safe_subject, subject_redactions = sanitize(subject.json())
    safe_patch, patch_redactions = sanitize(git_evidence.patch.json())
    safe_tests, test_redactions = sanitize(_tests(chapter_list))
    all_redactions.extend(subject_redactions)
    all_redactions.extend(patch_redactions)
    all_redactions.extend(test_redactions)
    generated_at = str(policy.get("generated_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    observed_test_result = any(test["outcome"] in {"passed", "failed"} for test in safe_tests)
    complete_required = bool(any(chapter["prompts"] for chapter in rendered_chapters) and any(chapter["events"] for chapter in rendered_chapters) and safe_patch.get("text") and observed_test_result and any(chapter["execution_spans"] for chapter in rendered_chapters))
    current = {"complete": not omissions and complete_required, "capture_mode": capture_mode,
               "capture_fidelity": "exact" if all(c.capture_fidelity == "exact" for c in chapter_list) else "partial",
               "generated_at": generated_at}
    payload: dict[str, Any] = {"schema": SCHEMA, "subject": safe_subject, "current": current,
        "chapters": rendered_chapters, "patch": safe_patch, "tests": safe_tests,
        "provenance": {"adapter": {"value": "team-room-evidence/v1", "source": "observed"}}, "redactions": _merge_redactions(all_redactions),
        "omissions": [{"category": item.category, "reason": item.reason} for item in omissions]}
    payload["rendered_markdown"] = _render(safe_subject, rendered_chapters, safe_patch, safe_tests, omissions)
    # A caller may narrow the cap but can never broaden the upload contract.
    maximum = min(int(policy.get("max_bytes", DEFAULT_MAX_BYTES)), DEFAULT_MAX_BYTES)
    data = _encode(payload)
    if len(data) > maximum:
        # First degradation tier: drop raw tool-result excerpts while preserving
        # prompts, decisions, paths/stats, test evidence, and provenance.
        for chapter in payload["chapters"]:
            for event in chapter["events"]:
                if event["type"] == "tool_result" and event["summary"]:
                    event["summary"] = "[tool result omitted for size]"
                    event["data"] = {}
                    omissions.append(Omission("tool_result", "omitted to satisfy artifact size policy"))
        payload["current"]["complete"] = False
        payload["omissions"] = [{"category": item.category, "reason": item.reason} for item in omissions]
        payload["rendered_markdown"] = _render(safe_subject, payload["chapters"], safe_patch, safe_tests, omissions)
        data = _encode(payload)
    if len(data) > maximum:
        # Second tier: context that is not a prompt, decision, path/stat, test,
        # or provenance becomes an explicit omission. Those retained facts are
        # the minimum evidence fields promised by the size limit.
        for chapter in payload["chapters"]:
            for event in chapter["events"]:
                if event["type"] == "agent_message" and event["summary"]:
                    event["summary"] = "[unchanged context omitted for size]"
                    omissions.append(Omission("unchanged_context", "omitted to satisfy artifact size policy"))
        payload["current"]["complete"] = False
        payload["omissions"] = [{"category": item.category, "reason": item.reason} for item in omissions]
        payload["rendered_markdown"] = _render(safe_subject, payload["chapters"], safe_patch, safe_tests, omissions)
        data = _encode(payload)
    if len(data) > maximum:
        # Third tier: a session so large that even excerpt-stripped metadata
        # outgrows the cap (a 14k-event build session is megabytes of ids and
        # timestamps alone). Keep the arc — the first and last `window` events
        # of each chapter — and replace the middle with one explicit omission
        # carrying exact per-type counts; each chapter also gains truthful
        # `event_counts` totals over the FULL event list so downstream
        # summaries never understate the session. Halving the window
        # converges to a skeleton that always fits: a big session may
        # degrade, but it can never fail to publish.
        pristine = [list(chapter["events"]) for chapter in payload["chapters"]]
        window = 512
        while len(data) > maximum:
            attempt_omissions = list(omissions)
            for chapter, events in zip(payload["chapters"], pristine):
                counts: dict[str, int] = {}
                for event in events:
                    counts[event["type"]] = counts.get(event["type"], 0) + 1
                chapter["event_counts"] = counts
                if len(events) <= 2 * window:
                    chapter["events"] = list(events)
                    continue
                kept = events[:window] + events[len(events) - window :] if window else []
                dropped = events[window : len(events) - window] if window else events
                dropped_counts: dict[str, int] = {}
                for event in dropped:
                    dropped_counts[event["type"]] = dropped_counts.get(event["type"], 0) + 1
                detail = ", ".join(f"{count} {kind}" for kind, count in sorted(dropped_counts.items()))
                attempt_omissions.append(Omission(
                    "event_window",
                    f"{len(dropped)} events omitted to satisfy artifact size policy ({detail}); "
                    f"first and last {window} kept; event_counts holds full totals",
                ))
                chapter["events"] = kept
            payload["current"]["complete"] = False
            payload["omissions"] = [{"category": item.category, "reason": item.reason} for item in attempt_omissions]
            payload["rendered_markdown"] = _render(safe_subject, payload["chapters"], safe_patch, safe_tests, attempt_omissions)
            data = _encode(payload)
            if window == 0:
                break
            window //= 2
    # One final full-object pass covers policy-derived fields and the rendering
    # immediately before bytes are written.
    payload, final_redactions = sanitize(payload)
    payload["redactions"] = _merge_redactions([*all_redactions, *final_redactions])
    _validate_payload(payload)
    data = _encode(payload)
    if len(data) > maximum:
        raise ValueError("artifact exceeds the configured size policy after safe degradation")
    output_dir = Path(policy.get("output_dir", Path.cwd() / ".pr-evidence"))
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    fd, temporary = tempfile.mkstemp(prefix="pr-evidence-", suffix=".json", dir=output_dir)
    final = output_dir / "pr-evidence-current.json"
    try:
        with os.fdopen(fd, "wb") as handle:
            os.chmod(temporary, 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, final)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    checkpoint = policy.get("checkpoint")
    return BundleResult(str(final), hashlib.sha256(data).hexdigest(), len(data), bool(payload["current"]["complete"]), tuple(omissions), payload["rendered_markdown"], checkpoint)

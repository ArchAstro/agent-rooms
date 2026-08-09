"""Optimistic current-artifact publication with head ordering and recovery."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

from .artifacts import ArtifactValidationError, encode_artifact, semantic_hash, validate_content
from .policy import Policy, restrict_payload
from .retry import clear_retry, save_retry
from .sanitize import sanitize, SanitizationError
from .bundle import rebuild_payload

CLIENT_SOURCE = "rooms-skill"


@dataclass(frozen=True)
class PublishRequest:
    subject_key: str
    artifact_name: str
    prior_head: str
    head_sha: str
    session_id: str
    content: Mapping[str, Any]
    replace_head_from: str | None = None
    from_artifact_version: int | None = None
    is_fast_forward: bool = False


@dataclass(frozen=True)
class PublishResult:
    status: str
    artifact_id: str | None = None
    version: int | None = None
    stats: Mapping[str, int] | None = None
    content: Mapping[str, Any] | None = None
    summary_error: str | None = None


class ArtifactClient:
    """Exact bounded client for firstlanding's developer artifact API."""
    def __init__(self, server: str, app_id: str, team_id: str, thread_id: str, token: str, user_id: str):
        self.app_base = server.rstrip("/") + f"/protected/api/v1/developer/apps/{app_id}"
        self.team_id, self.thread_id, self.token, self.user_id = team_id, thread_id, token, user_id

    def _call(
        self,
        method: str,
        url: str,
        body: Mapping[str, Any] | None = None,
        timeout: float = 8,
    ) -> Any:
        data = None if body is None else json.dumps(body, separators=(",", ":"), allow_nan=False).encode()
        if data is not None and len(data) > 5 * 1024 * 1024:
            raise ValueError("artifact request exceeds bounded JSON envelope")
        request = urllib.request.Request(url, data=data, method=method,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}", "User-Agent": "room-post/pr-evidence-v1", "X-Client-Source": CLIENT_SOURCE})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024: raise ArtifactValidationError("artifact response exceeds byte limit")
        decoded = json.loads(raw)
        if not isinstance(decoded, Mapping): raise ArtifactValidationError("artifact API response must be an object")
        value = decoded.get("data", decoded)
        if not isinstance(value, Mapping) and not isinstance(value, list): raise ArtifactValidationError("artifact API response data is malformed")
        return value

    def _content(self, artifact_id: str, version: int | None = None) -> dict[str, Any]:
        url = self.app_base + "/artifacts/" + urllib.parse.quote(artifact_id, safe="") + "/content"
        if version is not None:
            url += "?" + urllib.parse.urlencode({"version": version})
        request = urllib.request.Request(url,
            headers={"Authorization": f"Bearer {self.token}", "User-Agent": "room-post/pr-evidence-v1", "X-Client-Source": CLIENT_SOURCE})
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read(3 * 1024 * 1024 + 1)
        if len(raw) > 3 * 1024 * 1024: raise ArtifactValidationError("artifact content exceeds byte limit")
        value = json.loads(raw)
        if not isinstance(value, Mapping): raise ArtifactValidationError("artifact content must be an object")
        return dict(value)

    def list_artifacts(self):
        value = self._call("GET", self.app_base + "/teams/" + urllib.parse.quote(self.team_id, safe="") + "/artifacts")
        return value.get("data", value) if isinstance(value, Mapping) else value
    def show_artifact(self, artifact_id: str, version: int | None = None):
        artifact = self._call("GET", self.app_base + "/artifacts/" + urllib.parse.quote(artifact_id, safe=""))
        if not isinstance(artifact, Mapping): raise ArtifactValidationError("artifact metadata is malformed")
        output = dict(artifact); output["content"] = self._content(artifact_id, version); return output
    def create_artifact(self, name: str, content: Mapping[str, Any]):
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        encoded, _ = encode_artifact(raw)
        return self._call("POST", self.app_base + "/artifacts", {"name": name, "team": self.team_id, "thread": self.thread_id, "idempotency_key": "pr-evidence:create:" + name, "file": {"data": encoded.decode("ascii"), "filename": "pr-evidence.json", "mime_type": "application/json"}})
    def update_artifact(self, artifact_id: str, content: Mapping[str, Any], from_version: int):
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        encoded, _ = encode_artifact(raw)
        return self._call("PUT", self.app_base + "/artifacts/" + urllib.parse.quote(artifact_id, safe=""), {"from_version": from_version, "file": {"data": encoded.decode("ascii"), "filename": "pr-evidence.json", "mime_type": "application/json"}})
    def list_messages(self):
        value = self._call("GET", self.app_base + "/threads/" + urllib.parse.quote(self.thread_id, safe="") + "/messages")
        return value.get("data", value) if isinstance(value, Mapping) else value
    def show_message(self, message_id: str):
        return self._call(
            "GET",
            self.app_base
            + "/threads/"
            + urllib.parse.quote(self.thread_id, safe="")
            + "/messages/"
            + urllib.parse.quote(message_id, safe=""),
            timeout=1,
        )
    def create_message(self, content: str, idempotency_key: str, attachments: list[dict[str, str]] | None = None, metadata: Mapping[str, Any] | None = None):
        body: dict[str, Any] = {
            "content": content,
            "user": self.user_id,
            "idempotency_key": idempotency_key,
            "type": "exhaust",
        }
        if attachments: body["attachments"] = attachments
        if metadata: body["metadata"] = dict(metadata)
        return self._call(
            "POST",
            self.app_base + "/threads/" + urllib.parse.quote(self.thread_id, safe="") + "/messages",
            body,
            timeout=2,
        )
    def update_message(self, message_id: str, content: str, metadata: Mapping[str, Any], message_type: str = "exhaust"):
        return self._call(
            "PUT",
            self.app_base
            + "/threads/"
            + urllib.parse.quote(self.thread_id, safe="")
            + "/messages/"
            + urllib.parse.quote(message_id, safe=""),
            {"content": content, "metadata": dict(metadata), "type": message_type},
            timeout=2,
        )
class Publisher:
    def __init__(self, client: Any, state_path: Path, policy: Policy, ancestor: Callable[[str, str], bool] | None = None, summary_factory: Callable[[Mapping[str, Any], str], Mapping[str, Any]] | None = None):
        self.client, self.state_path, self.policy = client, state_path, policy
        self.ancestor = ancestor or (lambda _old, _new: False)
        self.summary_factory = summary_factory
        self.team_id, self.thread_id = getattr(client, "team_id", None), getattr(client, "thread_id", None)

    def _remote(self, artifact: Mapping[str, Any], name: str, subject: str) -> dict[str, Any]:
        return self.validate_remote(artifact, name, subject, self.team_id, self.thread_id)

    @staticmethod
    def validate_remote(artifact: Mapping[str, Any], name: str, subject_key: str, team_id: str | None = None, thread_id: str | None = None) -> dict[str, Any]:
        if not isinstance(artifact.get("id"), str) or artifact.get("name") != name or not isinstance(artifact.get("version"), int) or artifact["version"] < 1:
            raise ArtifactValidationError("remote artifact identity or version is invalid")
        if team_id is not None and artifact.get("team") != team_id:
            raise ArtifactValidationError("remote artifact team does not match configured room")
        if thread_id is not None and artifact.get("thread") != thread_id:
            raise ArtifactValidationError("remote artifact thread does not match configured room")
        if artifact.get("file_name") != "pr-evidence.json" or artifact.get("content_type") != "application/json":
            raise ArtifactValidationError("remote artifact file metadata is invalid")
        content = validate_content(artifact.get("content"), subject_key, name)
        return {"id": artifact["id"], "name": name, "version": artifact["version"], "content": content}

    def _state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError): return {}

    def _trusted_state(self) -> dict[str, Any] | None:
        """Read state that is private enough to authorize head replacement."""
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.state_path, flags)
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                metadata = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                    or metadata.st_size > 5 * 1024 * 1024
                ):
                    return None
                raw = handle.read(5 * 1024 * 1024 + 1)
            if len(raw.encode("utf-8")) > 5 * 1024 * 1024:
                return None
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except (OSError, UnicodeError, ValueError):
            return None

    def _save_state(self, request: PublishRequest, artifact: Mapping[str, Any], content: Mapping[str, Any], pending: str | None = None, message_id: str | None = None, summary_message_id: str | None = None, summary_hash: str | None = None):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        import fcntl
        with self.state_path.with_suffix(self.state_path.suffix + ".global.lock").open("a+") as lock:
            # State loss is worse than a deferred publication; bounded lock
            # acquisition avoids a wedged peer stalling a PR command forever.
            deadline = time.monotonic() + 0.5
            while True:
                try: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic() >= deadline: raise TimeoutError("evidence state lock busy")
                    time.sleep(0.01)
            try:
                state = self._state()
                previous = state.get(request.subject_key, {})
                state[request.subject_key] = {"artifact_id": artifact["id"], "message_id": message_id or previous.get("message_id"), "summary_message_id": summary_message_id or previous.get("summary_message_id"), "summary_hash": summary_hash or previous.get("summary_hash"), "artifact_version": artifact["version"], "head_sha": request.head_sha, "content_hash": semantic_hash(content), "message_pending": pending}
                fd, temp = tempfile.mkstemp(prefix=self.state_path.name + ".", dir=self.state_path.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as out:
                        os.chmod(temp, 0o600); json.dump(state, out, sort_keys=True, separators=(",", ":")); out.flush(); os.fsync(out.fileno())
                    os.replace(temp, self.state_path); os.chmod(self.state_path, 0o600)
                finally:
                    if os.path.exists(temp): os.unlink(temp)
            finally: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _merge(remote: Mapping[str, Any], local: Mapping[str, Any], session_id: str) -> dict[str, Any]:
        merged = json.loads(json.dumps(remote))
        current = dict(local)
        chapters = list(merged.get("chapters", []))
        replacement = [chapter for chapter in current.get("chapters", []) if chapter.get("session_id") == session_id]
        if len(replacement) != 1: raise ArtifactValidationError("local artifact must contain exactly one current session chapter")
        chapters = [chapter for chapter in chapters if chapter.get("session_id") != session_id] + replacement
        chapters.sort(key=lambda chapter: chapter["session_id"])
        redactions: dict[str, int] = {}
        for item in [*remote.get("redactions", []), *local.get("redactions", [])]:
            if isinstance(item, Mapping) and isinstance(item.get("category"), str) and isinstance(item.get("count"), int):
                redactions[item["category"]] = max(redactions.get(item["category"], 0), item["count"])
        omissions = {
            (item["category"], item["reason"])
            for item in [*remote.get("omissions", []), *local.get("omissions", [])]
            if isinstance(item, Mapping)
            and isinstance(item.get("category"), str)
            and isinstance(item.get("reason"), str)
        }
        provenance = dict(remote.get("provenance", {}))
        provenance.update(local.get("provenance", {}))
        merged.update(current)
        merged["chapters"] = chapters
        merged["redactions"] = [
            {"category": category, "count": redactions[category]}
            for category in sorted(redactions)
        ]
        merged["omissions"] = [
            {"category": category, "reason": reason}
            for category, reason in sorted(omissions)
        ]
        merged["provenance"] = provenance
        return rebuild_payload(merged, chapters)

    @staticmethod
    def _is_conflict(exc: Exception) -> bool:
        return "409" in str(exc) or (isinstance(exc, urllib.error.HTTPError) and exc.code == 409)

    def _message_key(self, request: PublishRequest) -> str:
        return "pr-evidence:initial:" + request.subject_key

    def _summary_key(self, request: PublishRequest) -> str:
        return "pr-evidence:summary:" + request.subject_key

    @staticmethod
    def _attachment_key(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        for prefix in ("art_", "mat_"):
            if value.startswith(prefix):
                return value[len(prefix):]
        return value

    @classmethod
    def _has_artifact_attachment(
        cls, message: object, artifact: Mapping[str, Any]
    ) -> bool:
        nested = message.get("data", message) if isinstance(message, Mapping) else None
        if not isinstance(nested, Mapping) or not isinstance(nested.get("attachments"), list):
            return False
        expected = cls._attachment_key(artifact.get("id"))
        return any(
            isinstance(item, Mapping)
            and item.get("type") == "artifact"
            and cls._attachment_key(item.get("id")) == expected
            for item in nested["attachments"]
        )

    def _has_initial_message(
        self, request: PublishRequest, artifact: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        key = self._message_key(request)
        return next(
            (
                message
                for message in self.client.list_messages()
                if isinstance(message, Mapping)
                and message.get("idempotency_key") == key
                and self._has_artifact_attachment(message, artifact)
            ),
            None,
        )

    def _initial_message(self, request: PublishRequest, artifact: Mapping[str, Any]) -> Any:
        existing = self._has_initial_message(request, artifact)
        if existing:
            return existing
        key = self._message_key(request)
        for attempt in range(2):
            message = self.client.create_message(
                (
                    f"PR evidence for {request.subject_key} is attached. "
                    "Open it to review the prompt, trajectory, and change "
                    "evidence allowed by the team's capture mode; this "
                    "attachment follows the current complete version."
                ),
                key,
                [{"id": artifact["id"], "type": "artifact"}],
            )
            if not hasattr(self.client, "show_message"):
                # Older compatible clients cannot perform the authoritative
                # confirmation; retain their pre-v1 behavior.
                return message
            candidate = message
            message_id = self._message_id(message)
            if message_id:
                candidate = self.client.show_message(message_id)
            if self._has_artifact_attachment(candidate, artifact):
                return candidate
            if attempt == 0:
                # Production artifact materialization can lag the successful
                # message response by a fraction of a second. One bounded,
                # idempotent retry keeps PR creation fast and duplicate-free.
                time.sleep(0.25)
        raise ArtifactValidationError("initial PR evidence attachment did not materialize")

    @staticmethod
    def _message_value(message: Any) -> Mapping[str, Any] | None:
        if not isinstance(message, Mapping):
            return None
        nested = message.get("data", message)
        return nested if isinstance(nested, Mapping) else None

    def _summary_message(self, request: PublishRequest, result: PublishResult) -> None:
        if self.summary_factory is None or result.content is None or result.artifact_id is None:
            return
        desired = dict(self.summary_factory(result.content, result.artifact_id))
        content = desired.get("content")
        metadata = desired.get("metadata")
        message_type = desired.get("type", "exhaust")
        if not isinstance(content, str) or not isinstance(metadata, Mapping) or not isinstance(message_type, str):
            raise ArtifactValidationError("summary factory returned an invalid message")
        desired_hash = semantic_hash({"content": content, "metadata": metadata, "type": message_type})
        state = self._state().get(request.subject_key, {})
        message = None
        trusted_id = state.get("summary_message_id") if isinstance(state, Mapping) else None
        if isinstance(trusted_id, str) and trusted_id:
            try:
                message = self.client.show_message(trusted_id)
            except Exception:
                message = None
        recovered = False
        if message is None:
            key = self._summary_key(request)
            message = next(
                (
                    item for item in self.client.list_messages()
                    if isinstance(item, Mapping) and item.get("idempotency_key") == key
                ),
                None,
            )
            recovered = message is not None
        value = self._message_value(message)
        message_id = self._message_id(message)
        matches = (
            value is not None
            and value.get("content") == content
            and value.get("metadata") == metadata
            and value.get("type") == message_type
        )
        if message_id is None:
            message = self.client.create_message(
                content,
                self._summary_key(request),
                metadata=metadata,
            )
            message_id = self._message_id(message)
        elif recovered or not matches:
            message = self.client.update_message(message_id, content, metadata, message_type)
            message_id = self._message_id(message) or message_id
        if not isinstance(message_id, str) or not message_id:
            raise ArtifactValidationError("summary message did not return an id")
        self._save_state(
            request,
            {"id": result.artifact_id, "version": result.version},
            result.content,
            summary_message_id=message_id,
            summary_hash=desired_hash,
        )

    def _current_after_initial_message(self, request: PublishRequest, artifact: Mapping[str, Any]) -> dict[str, Any]:
        """Do not turn an attachment effect into false ownership of a newer current pointer."""
        current = self._remote(self.client.show_artifact(artifact["id"]), request.artifact_name, request.subject_key)
        if (
            current["id"] != artifact["id"]
            or current["version"] != artifact["version"]
            or current["content"]["subject"]["head_sha"] != request.head_sha
        ):
            raise ArtifactValidationError("artifact advanced while recording initial attachment")
        return current

    @staticmethod
    def _message_id(response: Any) -> str | None:
        if isinstance(response, Mapping):
            nested = response.get("data", response)
            return nested.get("id") if isinstance(nested, Mapping) and isinstance(nested.get("id"), str) else None
        return None

    def _head_is_allowed(
        self,
        remote: Mapping[str, Any],
        request: PublishRequest,
        state: Mapping[str, Any] | None = None,
    ) -> bool:
        existing_head = remote["content"]["subject"]["head_sha"]
        if existing_head == request.head_sha:
            return True
        explicit_replacement = (
            request.replace_head_from == existing_head
            and request.from_artifact_version == remote["version"]
        )
        confirmed_local_replacement = (
            isinstance(state, Mapping)
            and state.get("artifact_id") == remote["id"]
            and state.get("artifact_version") == remote["version"]
            and state.get("head_sha") == existing_head
            and state.get("content_hash") == semantic_hash(remote["content"])
            and isinstance(state.get("message_id"), str)
            and bool(state["message_id"])
            and state.get("message_pending") is None
        )
        return (
            self.ancestor(existing_head, request.head_sha)
            or explicit_replacement
            or confirmed_local_replacement
        )

    def _show_written_version(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        """Read the immutable content written by our successful CAS when supported."""
        try:
            return self.client.show_artifact(artifact_id, version)
        except TypeError:
            # Older local test doubles and servers expose current-only reads.
            # Production ArtifactClient supports the versioned content read.
            return self.client.show_artifact(artifact_id)

    def _validated_written(
        self,
        response: Any,
        request: PublishRequest,
        expected_content: Mapping[str, Any],
        expected_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        if (
            not isinstance(response, Mapping)
            or not isinstance(response.get("id"), str)
            or not isinstance(response.get("version"), int)
            or response["version"] < 1
        ):
            raise ArtifactValidationError("write returned invalid artifact identity or version")
        if expected_artifact_id is not None and response["id"] != expected_artifact_id:
            raise ArtifactValidationError("write response substituted a different artifact")
        written_version = response["version"]
        observed = dict(self._show_written_version(response["id"], written_version))
        # The artifact metadata endpoint may report a newer current version
        # while its versioned content endpoint returned the requested one.
        # Bind the validated content to the CAS version from the write response.
        observed["version"] = written_version
        written = self._remote(observed, request.artifact_name, request.subject_key)
        if (
            written["content"]["subject"]["head_sha"] != request.head_sha
            or semantic_hash(written["content"]) != semantic_hash(expected_content)
        ):
            raise ArtifactValidationError("written artifact version does not match the requested head and content")
        return written

    def _queue(self, request: PublishRequest, reason: str, artifact: Mapping[str, Any] | None = None) -> PublishResult:
        saved = save_retry(self.state_path.with_name("pr-evidence-retry.json"), {"subject_key": request.subject_key, "artifact_id": (artifact or {}).get("id"), "artifact_name": request.artifact_name, "head_sha": request.head_sha, "content_hash": semantic_hash(request.content), "reason": reason})
        return PublishResult("queued" if saved else "withheld", (artifact or {}).get("id"), (artifact or {}).get("version"))

    def _publish_unlocked(self, request: PublishRequest) -> PublishResult:
        try:
            safe, _ = sanitize(dict(request.content))
            content = restrict_payload(safe, self.policy)
            content.setdefault("current", {})["generated_at"] = content.get("current", {}).get("generated_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if len(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")) > self.policy.max_bytes:
                return PublishResult("withheld")
        except (SanitizationError, ValueError, TypeError):
            return PublishResult("withheld")
        try:
            trusted_state = self._trusted_state()
            state_document = trusted_state if trusted_state is not None else self._state()
            state = state_document.get(request.subject_key, {})
            replacement_state = (
                trusted_state.get(request.subject_key, {})
                if trusted_state is not None
                else None
            )
            artifact = None
            cold_recovery = False
            aid = state.get("artifact_id") if isinstance(state, Mapping) else None
            if isinstance(aid, str): artifact = self.client.show_artifact(aid)
            else:
                matches = [item for item in self.client.list_artifacts() if isinstance(item, Mapping) and item.get("name") == request.artifact_name]
                if len(matches) > 1: return PublishResult("withheld")
                artifact = self.client.show_artifact(matches[0]["id"]) if matches else None
                cold_recovery = artifact is not None
            if artifact is None:
                created = self.client.create_artifact(request.artifact_name, content)
                created = self._validated_written(created, request, content)
                # The artifact is durable before a response-lost message can
                # be retried. The deterministic key makes this recovery safe.
                self._save_state(request, created, content, "initial")
                message = self._initial_message(request, created)
                created = self._current_after_initial_message(request, created)
                self._save_state(request, created, content, message_id=self._message_id(message))
                return PublishResult("published", created["id"], created["version"], content=created["content"])
            remote = self._remote(artifact, request.artifact_name, request.subject_key)
            cold_attachment_needed = False
            existing_initial_message = None
            if cold_recovery and not state:
                # Exact-name discovery is not proof this orphan belongs to the
                # requested PR head. Reject it before policy rewriting, state,
                # or an attachment can make that false adoption durable.
                if not self._head_is_allowed(remote, request, replacement_state):
                    return PublishResult("withheld", remote["id"], remote["version"])
                # A create response may have vanished after the server stored
                # the artifact. Exact-name discovery plus a native message key
                # resumes at the next missing effect, never creates again.
                # The discovered artifact can predate a narrower local mode,
                # so enforce that mode before exposing it through the message.
                safe_remote, remote_redactions = sanitize(dict(remote["content"]))
                counts = {
                    item["category"]: item["count"]
                    for item in safe_remote.get("redactions", [])
                    if isinstance(item, Mapping) and isinstance(item.get("category"), str) and isinstance(item.get("count"), int)
                }
                for item in remote_redactions:
                    counts[item.category] = max(counts.get(item.category, 0), item.count)
                safe_remote["redactions"] = [
                    {"category": category, "count": counts[category]}
                    for category in sorted(counts)
                ]
                recovered = restrict_payload(safe_remote, self.policy)
                if semantic_hash(recovered) != semantic_hash(remote["content"]):
                    updated = self.client.update_artifact(remote["id"], recovered, remote["version"])
                    # Restriction never changes the subject head, so validate
                    # this exact CAS version against its pre-write head.
                    recovery_request = PublishRequest(
                        request.subject_key, request.artifact_name, request.prior_head,
                        remote["content"]["subject"]["head_sha"], request.session_id,
                        recovered,
                    )
                    remote = self._validated_written(updated, recovery_request, recovered, remote["id"])
                existing_initial_message = self._has_initial_message(request, remote)
                cold_attachment_needed = existing_initial_message is None
            # A response-loss retry is also a recovery path. Recheck the
            # current head before either attaching or recording its outcome.
            if not self._head_is_allowed(remote, request, replacement_state):
                return PublishResult("withheld", remote["id"], remote["version"])
            if isinstance(state, Mapping) and state.get("message_pending") == "initial":
                message = self._initial_message(request, remote)
                remote = self._current_after_initial_message(request, remote)
                self._save_state(request, remote, remote["content"], message_id=self._message_id(message))
                return PublishResult("published", remote["id"], remote["version"], content=remote["content"])
            # The remote artifact may contain earlier full-capsule chapters.
            # Apply the effective local mode only after merge so no retained
            # chapter or derived convenience rendering can bypass it.
            merged = restrict_payload(self._merge(remote["content"], content, request.session_id), self.policy)
            # Preserve the server's timestamp for semantic equality.
            merged.setdefault("current", {})["generated_at"] = remote["content"].get("current", {}).get("generated_at")
            if semantic_hash(merged) == semantic_hash(remote["content"]):
                self._save_state(
                    request,
                    remote,
                    remote["content"],
                    message_id=self._message_id(existing_initial_message),
                )
                if cold_attachment_needed:
                    self._save_state(request, remote, remote["content"], "initial")
                    message = self._initial_message(request, remote)
                    remote = self._current_after_initial_message(request, remote)
                    self._save_state(request, remote, remote["content"], message_id=self._message_id(message))
                    return PublishResult("published", remote["id"], remote["version"], content=remote["content"])
                return PublishResult("unchanged", remote["id"], remote["version"], content=remote["content"])
            for attempt in range(2):
                try:
                    self._save_state(request, remote, merged, "update")
                    updated = self.client.update_artifact(remote["id"], merged, remote["version"])
                    updated = self._validated_written(updated, request, merged, remote["id"])
                    self._save_state(
                        request,
                        updated,
                        merged,
                        message_id=self._message_id(existing_initial_message),
                    )
                    if cold_attachment_needed:
                        self._save_state(request, updated, merged, "initial")
                        message = self._initial_message(request, updated)
                        updated = self._current_after_initial_message(request, updated)
                        self._save_state(request, updated, merged, message_id=self._message_id(message))
                        return PublishResult("published", updated["id"], updated["version"], content=updated["content"])
                    return PublishResult("updated", updated["id"], updated["version"], content=updated["content"])
                except Exception as exc:
                    if not self._is_conflict(exc) or attempt: return self._queue(request, "version_conflict", remote)
                    remote = self._remote(self.client.show_artifact(remote["id"]), request.artifact_name, request.subject_key)
                    if not self._head_is_allowed(remote, request, replacement_state):
                        return PublishResult("withheld", remote["id"], remote["version"])
                    merged = restrict_payload(self._merge(remote["content"], content, request.session_id), self.policy)
                    merged.setdefault("current", {})["generated_at"] = remote["content"].get("current", {}).get("generated_at")
                    if semantic_hash(merged) == semantic_hash(remote["content"]):
                        self._save_state(
                            request,
                            remote,
                            remote["content"],
                            message_id=self._message_id(existing_initial_message),
                        )
                        return PublishResult("unchanged", remote["id"], remote["version"], content=remote["content"])
            return self._queue(request, "version_conflict", remote)
        except Exception as exc:
            return self._queue(request, type(exc).__name__)

    def publish(self, request: PublishRequest) -> PublishResult:
        """Serialize the full subject transaction, including cold discovery."""
        import fcntl
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.state_path.with_name("pr-evidence-" + semantic_hash({"subject": request.subject_key})[:24] + ".lock")
        with lock_path.open("a+") as lock:
            deadline = time.monotonic() + 0.5
            while True:
                try: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic() >= deadline: return self._queue(request, "subject_lock_busy")
                    time.sleep(0.01)
            try:
                result = self._publish_unlocked(request)
                if result.status not in {"queued", "withheld"}:
                    clear_retry(
                        self.state_path.with_name("pr-evidence-retry.json"),
                        request.subject_key,
                    )
                    try:
                        self._summary_message(request, result)
                    except Exception as exc:
                        result = PublishResult(
                            result.status,
                            result.artifact_id,
                            result.version,
                            result.stats,
                            result.content,
                            f"{type(exc).__name__}: {str(exc)[:160]}",
                        )
                return result
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

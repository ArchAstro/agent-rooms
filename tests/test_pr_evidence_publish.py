#!/usr/bin/env python3
"""Real-TCP publication contract for one current PR evidence artifact."""
import base64
import http.server
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "skills" / "team-room" / "room_post.py"


class ContractServer(http.server.BaseHTTPRequestHandler):
    api = "/protected/api/v1/developer/apps/app-test"
    artifacts = {}
    messages = []
    writes = []
    reads = []
    lose_create_response = False
    lose_initial_message_response = False
    lose_update_message_response = False
    create_barrier = None

    def log_message(self, *_):
        pass

    def reply(self, status, value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.__class__.writes.append((self.command, self.path, raw))
        return json.loads(raw or b"{}")

    def do_GET(self):
        assert self.headers.get("Authorization") == "Bearer room-test-token"
        self.__class__.reads.append(self.path)
        parsed = urlsplit(self.path)
        if parsed.path == "/api/v1/users/me":
            self.reply(200, {"id": "user-test", "app_id": "app-test"})
        elif parsed.path == self.api + "/threads/thread-test":
            self.reply(200, {"members": [{"user": {"id": "user-test", "email": "test@example.invalid"}}]})
        elif parsed.path == self.api + "/teams/team-test/artifacts":
            self.reply(200, {"data": [self.metadata(item) for item in self.artifacts.values()]})
        elif parsed.path.startswith(self.api + "/artifacts/") and parsed.path.endswith("/content"):
            artifact = self.artifacts.get(parsed.path.split("/artifacts/", 1)[1].split("/", 1)[0])
            requested = parse_qs(parsed.query).get("version", [None])[0]
            raw = artifact["versions"].get(int(requested), b"") if artifact and requested else (artifact["raw"] if artifact else b"")
            self.send_response(200 if artifact else 404); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        elif parsed.path.startswith(self.api + "/artifacts/"):
            artifact = self.artifacts.get(parsed.path.rsplit("/", 1)[-1])
            self.reply(200 if artifact else 404, self.metadata(artifact) if artifact else {"error": "missing"})
        elif parsed.path == self.api + "/threads/thread-test/messages":
            self.reply(200, {"data": self.messages})
        else:
            self.reply(404, {"error": "missing"})

    @staticmethod
    def metadata(artifact):
        return {key: artifact[key] for key in ("id", "name", "version", "team", "thread", "file_url", "file_name", "content_type", "created_at", "updated_at")}

    def do_POST(self):
        assert self.headers.get("Authorization") == "Bearer room-test-token"
        body = self.body()
        if self.path == self.api + "/artifacts":
            assert body["team"] == "team-test" and body["thread"] == "thread-test", body
            assert body["file"]["filename"] == "pr-evidence.json" and body["file"]["mime_type"] == "application/json", body
            raw = base64.b64decode(body["file"]["data"], validate=True)
            value = json.loads(raw)
            barrier = self.__class__.create_barrier
            if barrier is not None:
                barrier.wait(timeout=5)
            aid = f"artifact-{len(self.artifacts) + 1}"
            artifact = {"id": aid, "name": body["name"], "version": 1, "team": "team-test", "thread": "thread-test", "file_url": f"/files/{aid}", "file_name": "pr-evidence.json", "content_type": "application/json", "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z", "raw": raw, "versions": {1: raw}}
            self.artifacts[aid] = artifact
            if self.__class__.lose_create_response:
                self.__class__.lose_create_response = False
                self.close_connection = True
                return
            self.reply(200, self.metadata(artifact))
        elif self.path == self.api + "/threads/thread-test/messages":
            assert body["user"] == "user-test" and body.get("idempotency_key", "").startswith("pr-evidence:"), body
            attachments = body.get("attachments", [])
            if attachments:
                assert len(attachments) == 1 and attachments[0].get("type") == "artifact" and attachments[0].get("id") in self.artifacts, attachments
            existing = next((m for m in self.messages if m.get("idempotency_key") == body.get("idempotency_key")), None)
            if existing:
                self.reply(200, {"data": existing}); return
            message = {"id": f"message-{len(self.messages) + 1}", **body}
            self.messages.append(message)
            lose = (
                attachments and self.__class__.lose_initial_message_response
            ) or (
                not attachments and self.__class__.lose_update_message_response
            )
            if lose:
                self.__class__.lose_initial_message_response = False
                self.__class__.lose_update_message_response = False
                self.close_connection = True
                return
            self.reply(200, {"data": message})
        else:
            self.reply(404, {"error": "missing"})

    def do_PUT(self):
        assert self.headers.get("Authorization") == "Bearer room-test-token"
        body = self.body()
        assert self.path.startswith(self.api + "/artifacts/")
        aid = self.path.rsplit("/", 1)[-1]
        artifact = self.artifacts[aid]
        assert body["from_version"] == artifact["version"], body
        assert body["file"]["filename"] == "pr-evidence.json" and body["file"]["mime_type"] == "application/json", body
        artifact["version"] += 1
        artifact["raw"] = base64.b64decode(body["file"]["data"], validate=True)
        artifact["versions"][artifact["version"]] = artifact["raw"]
        self.reply(200, self.metadata(artifact))


def git(cwd, *args):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def commit(cwd, text):
    (cwd / "evidence.txt").write_text(text)
    subprocess.run(["git", "add", "evidence.txt"], cwd=cwd, check=True)
    subprocess.run(["git", "commit", "-m", text], cwd=cwd, check=True, capture_output=True)
    return git(cwd, "rev-parse", "HEAD")


def producer(path):
    path.write_text("""#!/usr/bin/env python3
import json, os
s = os.environ['ROOM_EVIDENCE_SESSION_ID']
for n, kind, summary, data in [
    (1, 'human_prompt', 'Publish safe evidence', {}),
    (2, 'test', 'proof', {'command': 'python3 tests/test_pr_evidence_publish.py', 'outcome': 'passed'}),
]: print(json.dumps({'session_id': s, 'sequence': n, 'type': kind, 'summary': summary, 'data': data}))
""")
    path.chmod(0o700)


def credential_producer(path, credentials):
    path.write_text(f"""#!/usr/bin/env python3
import json, os
s = os.environ['ROOM_EVIDENCE_SESSION_ID']
credentials = {json.dumps(credentials)}
for event in [
    {{'session_id': s, 'sequence': 1, 'type': 'human_prompt', 'summary': 'Authorization: Bearer ' + credentials['jwt'], 'data': {{}}}},
    {{'session_id': s, 'sequence': 2, 'type': 'agent_message', 'summary': 'Slack credential ' + credentials['slack'], 'data': {{}}}},
    {{'session_id': s, 'sequence': 3, 'type': 'tool_result', 'summary': 'credential-bearing tool result', 'data': {{'database': credentials['database'], 'private_key': credentials['private_key']}}}},
]: print(json.dumps(event))
""")
    path.chmod(0o700)


def run_publish(
    repo,
    home,
    server,
    base,
    head,
    session,
    handoff_only=False,
    extra_env=None,
):
    room = home / "room.json"
    room.write_text(json.dumps({"thread_id": "thread-test", "team_id": "team-test", "server": server,
                                "portal": server, "app_slug": "test", "publishable_key": "pk"}))
    env = {**os.environ, "HOME": str(home), "ROOM_JSON": str(room), "TEAM_ROOM_TRUST_SERVER": "1",
           "TEAM_ROOM_TOKEN": "room-test-token", "ROOM_EVIDENCE_PRODUCER": str(home / "producer.py"),
           "GITHUB_TOKEN": "", "GH_TOKEN": "", "GITHUB_PAT": "", **(extra_env or {})}
    args = [sys.executable, str(KIT), "pr", "publish"]
    if handoff_only:
        handoff = home / "handoff.json"
        handoff.write_text(json.dumps({
            "pr_url": "https://github.com/owner/repository/pull/7",
            "base_ref": "main",
            "base_sha": base,
            "head_sha": head,
            "session_id": session,
            "harness": "generic",
            "agent_type": "astrodev",
            "model": "openai/gpt-test",
        }))
        handoff.chmod(0o600)
        args += ["--handoff", str(handoff)]
    else:
        args += ["https://github.com/owner/repository/pull/7", "--base-ref", "main", "--base-sha", base, "--head-sha", head]
        args += ["--session", session, "--harness", "generic"]
    return subprocess.run(args, cwd=repo, env=env,
                          text=True, capture_output=True, timeout=30)


def run_first_party_handoff(
    repo,
    home,
    server,
    base,
    head,
    session,
    harness,
    capture_lines,
    extra_env=None,
):
    room = home / "room.json"
    room.write_text(json.dumps({
        "thread_id": "thread-test",
        "team_id": "team-test",
        "server": server,
        "portal": server,
        "app_slug": "test",
        "publishable_key": "pk",
    }))
    capture = home / f"{harness}-capture.jsonl"
    capture.write_text(
        "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in capture_lines)
    )
    capture.chmod(0o600)
    handoff = home / f"{harness}-handoff.json"
    handoff.write_text(json.dumps({
        "pr_url": "https://github.com/owner/repository/pull/7",
        "base_ref": "main",
        "base_sha": base,
        "head_sha": head,
        "session_id": session,
        "harness": harness,
        "agent_type": "astrodev" if harness == "astrodev" else "codex",
        "model": "openai/gpt-test",
        "capture_path": str(capture),
    }))
    handoff.chmod(0o600)
    env = {
        **os.environ,
        "HOME": str(home),
        "ROOM_JSON": str(room),
        "TEAM_ROOM_TRUST_SERVER": "1",
        "TEAM_ROOM_TOKEN": "room-test-token",
        "ROOM_EVIDENCE_PRODUCER": "",
        "GITHUB_TOKEN": "",
        "GH_TOKEN": "",
        "GITHUB_PAT": "",
        **(extra_env or {}),
    }
    result = subprocess.run(
        [sys.executable, str(KIT), "pr", "publish", "--handoff", str(handoff)],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    return result, handoff, capture


def run_automatic_astrodev_envelope(
    repo,
    home,
    server,
    base,
    head,
    session_id,
    session_path,
    extra_payload=None,
    envelope_override=None,
):
    room = home / "room.json"
    room.write_text(json.dumps({
        "thread_id": "thread-test",
        "team_id": "team-test",
        "server": server,
        "portal": server,
        "app_slug": "test",
        "publishable_key": "pk",
    }))
    payload = {
        "pr_url": "https://github.com/owner/repository/pull/7",
        "base_ref": "main",
        "base_sha": base,
        "head_sha": head,
        "session_id": session_id,
        "session_cwd": str(repo),
        "session_path": str(session_path),
        "harness": "astrodev",
        "agent_type": "astrodev",
        **(extra_payload or {}),
    }
    header = json.dumps(payload, separators=(",", ":")).encode()
    envelope = (
        envelope_override
        if envelope_override is not None
        else len(header).to_bytes(4, "big") + header
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "ROOM_JSON": str(room),
        "TEAM_ROOM_TRUST_SERVER": "1",
        "TEAM_ROOM_TOKEN": "room-test-token",
        "ROOM_EVIDENCE_PRODUCER": "",
        "GITHUB_TOKEN": "",
        "GH_TOKEN": "",
        "GITHUB_PAT": "",
    }
    return subprocess.run(
        [sys.executable, str(KIT), "pr", "publish", "--envelope-stdin"],
        cwd=repo,
        env=env,
        input=envelope,
        capture_output=True,
        timeout=30,
    )


def reset_contract_server():
    ContractServer.artifacts = {}
    ContractServer.messages = []
    ContractServer.writes = []
    ContractServer.reads = []


def local_repo(root):
    repo = root / "repo"
    repo.mkdir()
    home = root / "home"
    home.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:owner/repository.git"],
        cwd=repo,
        check=True,
    )
    return repo, home, commit(repo, "base"), commit(repo, "head")


def test_two_agent_sessions_publish_one_current_artifact_over_tcp_without_github():
    """Two real CLI processes/Git commits/TCP writes converge without GitHub."""
    ContractServer.artifacts = {}; ContractServer.messages = []; ContractServer.writes = []; ContractServer.reads = []
    with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(("127.0.0.1", 0), ContractServer) as srv:
        root = Path(td); repo = root / "repo"; repo.mkdir(); home = root / "home"; home.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "remote", "add", "origin", "git@github.com:owner/repository.git"], cwd=repo, check=True)
        base = commit(repo, "base")
        first = commit(repo, "first")
        producer(home / "producer.py")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        endpoint = f"http://127.0.0.1:{srv.server_address[1]}"

        first_result = run_publish(repo, home, endpoint, base, first, "session-one")
        assert first_result.returncode == 0, first_result.stdout + first_result.stderr
        second = commit(repo, "second")
        second_result = run_publish(repo, home, endpoint, base, second, "session-two")
        assert second_result.returncode == 0, second_result.stdout + second_result.stderr
        assert "updated" in second_result.stdout, second_result.stdout + second_result.stderr

        artifact = ContractServer.artifacts["artifact-1"]
        content = json.loads(artifact["raw"])
        assert len(ContractServer.artifacts) == 1
        assert artifact["version"] == 2
        assert content["subject"]["head_sha"] == second
        assert [c["session_id"] for c in content["chapters"]] == ["session-one", "session-two"]
        assert sum(bool(m.get("attachments")) for m in ContractServer.messages) == 1
        assert len(ContractServer.messages) == 1

        before = len(ContractServer.writes)
        warm = run_publish(repo, home, endpoint, base, second, "session-two")
        assert warm.returncode == 0, warm.stdout + warm.stderr
        assert "unchanged" in warm.stdout
        assert len(ContractServer.writes) == before, ContractServer.writes[before:]
        assert any(path.endswith("/content") for path in ContractServer.reads)
        assert not any("github.com" in path for _, path, _ in ContractServer.writes)
    print("PASS  test_two_agent_sessions_publish_one_current_artifact_over_tcp_without_github")


def test_concurrent_cold_starts_can_duplicate_artifacts_until_the_server_honors_the_create_key():
    """The client sends a deterministic key, but the current fake has no create dedupe contract."""
    ContractServer.artifacts = {}; ContractServer.messages = []; ContractServer.writes = []; ContractServer.reads = []
    ContractServer.create_barrier = threading.Barrier(2)
    try:
        with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(("127.0.0.1", 0), ContractServer) as srv:
            root = Path(td); repo = root / "repo"; repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "remote", "add", "origin", "git@github.com:owner/repository.git"], cwd=repo, check=True)
            base = commit(repo, "base"); head = commit(repo, "head")
            homes = [root / "home-one", root / "home-two"]
            for home in homes:
                home.mkdir(); producer(home / "producer.py")
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            endpoint = f"http://127.0.0.1:{srv.server_address[1]}"
            results = [None, None]
            threads = [threading.Thread(target=lambda n=n: results.__setitem__(n, run_publish(repo, homes[n], endpoint, base, head, f"session-{n}"))) for n in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=15)

            creates = [json.loads(raw) for method, path, raw in ContractServer.writes if method == "POST" and path == ContractServer.api + "/artifacts"]
            assert len(creates) == 2
            assert len({item["name"] for item in creates}) == 1
            assert all(item.get("idempotency_key") == "pr-evidence:create:" + item["name"] for item in creates)
            assert len(ContractServer.artifacts) == 2
            assert all(result is not None and result.returncode == 0 for result in results)
    finally:
        ContractServer.create_barrier = None
    print("PASS  concurrent cold starts demonstrate missing server create dedupe")


def test_real_cli_redacts_credentials_before_the_room_http_write():
    """The real CLI sends only typed markers to the room TCP boundary."""
    ContractServer.artifacts = {}; ContractServer.messages = []; ContractServer.writes = []; ContractServer.reads = []
    credentials = {
        "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJzdXBlcm1hbiJ9.signature-value",
        "private_key": "-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSj\\n-----END PRIVATE KEY-----",
        "database": "postgresql://evidence_user:correct-horse-battery-staple@db.example.invalid:5432/evidence",
        "slack": "xoxb-123456789012-123456789012-abcdefghijklmnopqrstuvwxyzABCDEF",
        "api_token": "sk_live_1234567890abcdef",
    }
    with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(("127.0.0.1", 0), ContractServer) as srv:
        root = Path(td); repo = root / "repo"; repo.mkdir(); home = root / "home"; home.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "remote", "add", "origin", "git@github.com:owner/repository.git"], cwd=repo, check=True)
        base = commit(repo, "base")
        head = commit(repo, "\n".join(credentials.values()))
        credential_producer(home / "producer.py", credentials)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        result = run_publish(repo, home, f"http://127.0.0.1:{srv.server_address[1]}", base, head, "credential-session")
        assert result.returncode == 0, result.stdout + result.stderr

        stored = ContractServer.artifacts["artifact-1"]["raw"].decode()
        for name, secret in credentials.items():
            assert secret not in stored, f"{name} reached the stored room artifact"
        assert {item["category"] for item in json.loads(stored)["redactions"]} >= {
            "api_token", "bearer_token", "database_url", "private_key", "slack_token",
        }
        assert all(secret.encode() not in raw for _, _, raw in ContractServer.writes for secret in credentials.values())
    print("PASS  test_real_cli_redacts_credentials_before_the_room_http_write")


def test_persisted_tcp_response_loss_recovers_each_logical_effect_once():
    """Real CLI retries recover durable create and initial-attachment effects once."""
    for loss in ("create", "initial"):
        ContractServer.artifacts = {}; ContractServer.messages = []; ContractServer.writes = []; ContractServer.reads = []
        ContractServer.lose_create_response = loss == "create"
        ContractServer.lose_initial_message_response = loss == "initial"
        ContractServer.lose_update_message_response = False
        with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(("127.0.0.1", 0), ContractServer) as srv:
            root = Path(td); repo = root / "repo"; repo.mkdir(); home = root / "home"; home.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "remote", "add", "origin", "git@github.com:owner/repository.git"], cwd=repo, check=True)
            base = commit(repo, "base"); first = commit(repo, "first"); producer(home / "producer.py")
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            endpoint = f"http://127.0.0.1:{srv.server_address[1]}"
            first_try = run_publish(repo, home, endpoint, base, first, "session-one")
            assert first_try.returncode == 0
            if loss in {"create", "initial"}:
                recovered = run_publish(repo, home, endpoint, base, first, "session-one")
                assert recovered.returncode == 0 and "published" in recovered.stdout
            else:
                assert "published" in first_try.stdout
            assert len(ContractServer.artifacts) == 1
            assert sum(bool(message.get("attachments")) for message in ContractServer.messages) == 1

    print("PASS  persisted TCP response loss recovers create and one initial attachment once")


def test_pr_creation_handoff_runs_the_real_cli_without_github_credentials():
    """A creator-owned 0600 handoff crosses the real CLI and room TCP boundary."""
    ContractServer.artifacts = {}; ContractServer.messages = []; ContractServer.writes = []; ContractServer.reads = []
    with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(("127.0.0.1", 0), ContractServer) as srv:
        root = Path(td); repo = root / "repo"; repo.mkdir(); home = root / "home"; home.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        for key, value in (("user.email", "test@example.invalid"), ("user.name", "Test")):
            subprocess.run(["git", "config", key, value], cwd=repo, check=True)
        subprocess.run(["git", "remote", "add", "origin", "git@github.com:owner/repository.git"], cwd=repo, check=True)
        base = commit(repo, "base"); head = commit(repo, "head"); producer(home / "producer.py")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        result = run_publish(repo, home, f"http://127.0.0.1:{srv.server_address[1]}", base, head, "handoff-session", handoff_only=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout == "" and result.stderr == "", result.stdout + result.stderr
        assert not (home / "handoff.json").exists()
        artifact = json.loads(ContractServer.artifacts["artifact-1"]["raw"])
        assert artifact["subject"]["base_ref"] == "main"
        assert artifact["subject"]["base_sha"] == base
        assert artifact["subject"]["head_sha"] == head
        assert artifact["chapters"][0]["session_id"] == "handoff-session"
        span = artifact["chapters"][0]["execution_spans"][0]
        assert span["harness"] == {"value": "generic", "source": "agent_reported"}
        assert span["agent_type"] == {"value": "astrodev", "source": "harness_reported"}
        assert span["model"] == {"value": "openai/gpt-test", "source": "harness_reported"}
        assert not any("api.github.com" in path for path in ContractServer.reads)
        print("PASS  PR creation handoff publishes identity and provenance")


def test_astrodev_capture_runs_the_real_cli_without_generic_producer():
    """AstroDev's private session copy reaches the room without a producer env."""
    reset_contract_server()
    with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), ContractServer
    ) as srv:
        root = Path(td)
        repo, home, base, head = local_repo(root)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        result, handoff, capture = run_first_party_handoff(
            repo,
            home,
            f"http://127.0.0.1:{srv.server_address[1]}",
            base,
            head,
            "astrodev-session",
            "astrodev",
            [
                {
                    "type": "session",
                    "version": 3,
                    "id": "astrodev-session",
                    "timestamp": "2026-07-29T00:00:00Z",
                    "cwd": str(repo),
                    "binary": "archastro",
                    "cliVersion": "test",
                    "agent": {"id": "agent-1", "name": "AstroDev"},
                },
                {
                    "type": "message",
                    "timestamp": "2026-07-29T00:00:01Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "Fix the parser"}],
                        "timestamp": 1,
                    },
                },
                {
                    "type": "thinking",
                    "timestamp": "2026-07-29T00:00:02Z",
                    "content": "Inspecting the failing path",
                },
                {
                    "type": "tool_result",
                    "timestamp": "2026-07-29T00:00:03Z",
                    "name": "bash",
                    "input": {"command": "python3 tests/test_parser.py"},
                    "content": "1 passed",
                },
                {
                    "type": "message",
                    "timestamp": "2026-07-29T00:00:04Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Parser fixed"}],
                        "model": "openai/gpt-test",
                        "timestamp": 4,
                    },
                },
            ],
        )
        assert result.returncode == 0
        assert result.stdout == "" and result.stderr == "", result.stdout + result.stderr
        assert not handoff.exists() and not capture.exists()
        artifact = json.loads(ContractServer.artifacts["artifact-1"]["raw"])
        chapter = artifact["chapters"][0]
        assert chapter["session_id"] == "astrodev-session"
        assert chapter["prompts"] == ["Fix the parser"]
        assert [event["type"] for event in chapter["events"]] == [
            "human_prompt",
            "decision",
            "tool_result",
            "agent_message",
        ]
        assert "diff --git" in artifact["patch"]["text"]
        assert os.environ.get("ROOM_EVIDENCE_PRODUCER") is None


def test_issue_fixer_capture_keeps_both_real_codex_json_rounds():
    """The issue fixer preserves prompts and both raw Codex JSON event streams."""
    reset_contract_server()
    with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), ContractServer
    ) as srv:
        root = Path(td)
        repo, home, base, head = local_repo(root)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        result, handoff, capture = run_first_party_handoff(
            repo,
            home,
            f"http://127.0.0.1:{srv.server_address[1]}",
            base,
            head,
            "issue-fixer:owner/repository:42",
            "issue-fixer",
            [
                {
                    "type": "issue_fixer_session",
                    "session_id": "issue-fixer:owner/repository:42",
                },
                {
                    "type": "issue_fixer_prompt",
                    "round": "fixer",
                    "content": "Fix issue 42 with TDD",
                },
                {
                    "type": "codex_event",
                    "round": "fixer",
                    "event": {
                        "type": "thread.started",
                        "thread_id": "thread-fixer",
                    },
                },
                {
                    "type": "codex_event",
                    "round": "fixer",
                    "event": {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "python3 tests/test_fix.py",
                            "aggregated_output": "1 passed",
                            "exit_code": 0,
                        },
                    },
                },
                {
                    "type": "issue_fixer_prompt",
                    "round": "verifier",
                    "content": "Verify issue 42 independently",
                },
                {
                    "type": "codex_event",
                    "round": "verifier",
                    "event": {
                        "type": "thread.started",
                        "thread_id": "thread-verifier",
                    },
                },
                {
                    "type": "codex_event",
                    "round": "verifier",
                    "event": {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": "The fix is acceptable",
                        },
                    },
                },
            ],
        )
        assert result.returncode == 0
        assert result.stdout == "" and result.stderr == "", result.stdout + result.stderr
        assert not handoff.exists() and not capture.exists()
        artifact = json.loads(ContractServer.artifacts["artifact-1"]["raw"])
        chapter = artifact["chapters"][0]
        assert chapter["capture_fidelity"] == "partial"
        assert chapter["prompts"] == [
            "Fix issue 42 with TDD",
            "Verify issue 42 independently",
        ]
        assert [span["id"] for span in chapter["execution_spans"]] == [
            "issue-fixer:owner/repository:42",
            "thread-fixer",
            "thread-verifier",
        ]
        assert any(
            event["type"] == "tool_action"
            and event["data"]["command"] == "python3 tests/test_fix.py"
            for event in chapter["events"]
        )
        assert any(
            event["type"] == "agent_message"
            and event["summary"] == "The fix is acceptable"
            for event in chapter["events"]
        )


def test_issue_fixer_production_wrapper_crosses_real_cli_and_adapter():
    """The shipped issue-fixer wrapper publishes both real Codex JSON streams."""
    reset_contract_server()
    fixer_path = ROOT.parent / "firstlanding-wt5" / "tools" / "issues" / "fix_open_issues.py"
    if os.environ.get("RUN_FIRSTLANDING_INTEGRATION") != "1":
        print("SKIP  Firstlanding issue-fixer wrapper integration is opt-in")
        return
    if not fixer_path.is_file():
        print("SKIP  Firstlanding issue-fixer wrapper checkout is not available")
        return
    spec = importlib.util.spec_from_file_location("firstlanding_fix_open_issues", fixer_path)
    fixer_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixer_module)
    with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), ContractServer
    ) as srv:
        root = Path(td)
        repo, home, base, head = local_repo(root)
        endpoint = f"http://127.0.0.1:{srv.server_address[1]}"
        room = home / "room.json"
        room.write_text(json.dumps({
            "thread_id": "thread-test",
            "team_id": "team-test",
            "server": endpoint,
            "portal": endpoint,
            "app_slug": "test",
            "publishable_key": "pk",
        }))
        fake_bin = root / "bin"
        fake_bin.mkdir()
        (fake_bin / "room-post").symlink_to(KIT)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        streams = iter([
            (
                "fixer summary",
                [
                    {"type": "thread.started", "thread_id": "thread-fixer"},
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "python3 tests/test_fix.py",
                            "aggregated_output": "1 passed",
                            "exit_code": 0,
                        },
                    },
                ],
            ),
            (
                "verifier summary",
                [
                    {"type": "thread.started", "thread_id": "thread-verifier"},
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": "The fix is acceptable",
                        },
                    },
                ],
            ),
        ])

        def fake_codex(cmd, **_kwargs):
            summary, events = next(streams)
            Path(cmd[cmd.index("--output-last-message") + 1]).write_text(summary)
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="\n".join(json.dumps(event) for event in events),
                stderr="",
            )

        runner = fixer_module.CodexRunner(repo, command_runner=fake_codex)
        runner.run("Fix issue 42 with TDD", 30)
        runner.run("Verify issue 42 independently", 30)
        session = "issue-fixer:owner/repository:42"

        def fake_publish_command(cmd, **_kwargs):
            if cmd[:3] == ["gh", "pr", "create"]:
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout="https://github.com/owner/repository/pull/7\n",
                    stderr="",
                )
            if cmd[:2] == ["git", "rev-parse"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=base + "\n", stderr=""
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        publisher = fixer_module.GhPublisher(
            repo_root=repo,
            repo="owner/repository",
            command_runner=fake_publish_command,
            evidence_capture=runner.evidence_capture,
            model="openai/gpt-test",
        )
        previous = os.environ.copy()
        try:
            os.environ.update({
                "HOME": str(home),
                "ROOM_JSON": str(room),
                "TEAM_ROOM_TRUST_SERVER": "1",
                "TEAM_ROOM_TOKEN": "room-test-token",
                "ROOM_EVIDENCE_PRODUCER": "",
                "GITHUB_TOKEN": "",
                "GH_TOKEN": "",
                "GITHUB_PAT": "",
                "PATH": f"{fake_bin}{os.pathsep}{previous['PATH']}",
            })
            pr_url = publisher.publish(
                type("Issue", (), {"number": 42, "title": "Bound evidence"})(),
                "fix/issue-42-bound-evidence",
                head,
                "fixer summary",
                "verifier summary",
            )
        finally:
            os.environ.clear()
            os.environ.update(previous)

        assert pr_url == "https://github.com/owner/repository/pull/7"
        artifact = json.loads(ContractServer.artifacts["artifact-1"]["raw"])
        chapter = artifact["chapters"][0]
        assert chapter["prompts"] == [
            "Fix issue 42 with TDD",
            "Verify issue 42 independently",
        ]
        assert [span["id"] for span in chapter["execution_spans"]] == [
            session,
            "thread-fixer",
            "thread-verifier",
        ]
        prompt_spans = [
            event["execution_span_id"]
            for event in chapter["events"]
            if event["type"] == "human_prompt"
        ]
        assert prompt_spans == [session, session]
        assert "diff --git" in artifact["patch"]["text"]


def test_astrodev_production_wrapper_crosses_real_cli_and_adapter():
    """The shipped AstroDev wrapper copies its real session into the native adapter."""
    reset_contract_server()
    firstlanding = ROOT.parent / "firstlanding-wt5"
    package = firstlanding / "src" / "ts" / "developer-platform-tui"
    controller = (
        package / "src" / "develop" / "session-store" / "pr-create-controller.ts"
    )
    vite_node = firstlanding / "node_modules" / ".bin" / "vite-node"
    if os.environ.get("RUN_FIRSTLANDING_INTEGRATION") != "1":
        print("SKIP  Firstlanding AstroDev wrapper integration is opt-in")
        return
    if not controller.is_file():
        print("SKIP  Firstlanding AstroDev wrapper checkout is not available")
        return
    if not vite_node.is_file():
        print("SKIP  Firstlanding AstroDev wrapper dependencies are not installed")
        return
    with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), ContractServer
    ) as srv:
        root = Path(td)
        repo, home, base, head = local_repo(root)
        (repo / "scripts").mkdir()
        shutil.copy2(
            firstlanding / "scripts" / "room-post",
            repo / "scripts" / "room-post",
        )
        shutil.copytree(
            firstlanding / ".claude" / "skills" / "team-room",
            repo / ".claude" / "skills" / "team-room",
        )
        endpoint = f"http://127.0.0.1:{srv.server_address[1]}"
        room = home / "room.json"
        room.write_text(json.dumps({
            "thread_id": "thread-test",
            "team_id": "team-test",
            "server": endpoint,
            "portal": endpoint,
            "app_slug": "test",
            "publishable_key": "pk",
        }))
        session = home / "astrodev-session.jsonl"
        session.write_text("".join(
            json.dumps(record, separators=(",", ":")) + "\n"
            for record in [
                {
                    "type": "session",
                    "version": 3,
                    "id": "astrodev-production-session",
                    "timestamp": "2026-07-29T00:00:00Z",
                    "cwd": str(repo),
                    "binary": "archastro",
                    "cliVersion": "test",
                    "agent": {"id": "agent-1", "name": "AstroDev"},
                },
                {
                    "type": "message",
                    "timestamp": "2026-07-29T00:00:01Z",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "Fix production wrapper"}],
                        "timestamp": 1,
                    },
                },
                *[
                    {
                        "type": "thinking",
                        "timestamp": "2026-07-29T00:00:02Z",
                        "content": f"{index}:" + ("x" * 2048),
                    }
                    for index in range(800)
                ],
                {
                    "type": "tool_result",
                    "timestamp": "2026-07-29T00:00:03Z",
                    "name": "bash",
                    "input": {"command": "python3 tests/test_wrapper.py"},
                    "content": "1 passed",
                },
                {
                    "type": "message",
                    "timestamp": "2026-07-29T00:00:04Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Wrapper verified"}],
                        "model": "openai/gpt-test",
                        "timestamp": 3,
                    },
                },
            ]
        ))
        runner_fd, runner_name = tempfile.mkstemp(
            prefix=".astrodev-evidence-", suffix=".ts", dir=package
        )
        os.close(runner_fd)
        runner = Path(runner_name)
        runner.write_text(
            "import { PrCreateController, publishPrEvidence } from "
            + json.dumps(controller.as_uri())
            + ";\n"
            + "const controller = new PrCreateController({"
            + "cwd:"
            + json.dumps(str(repo))
            + ", transcript:{append(){}}, getProvider:()=>({}),"
            + "buildPlan:async()=>("
            + json.dumps({
                "base": base,
                "body": "Evidence integration",
                "branch": "feature",
                "remote": "owner/repository",
                "title": "Evidence integration",
            })
            + "), submit:async()=>"
            + json.dumps("https://github.com/owner/repository/pull/7")
            + ", getEvidenceContext:()=>("
            + json.dumps({
                "agentType": "astrodev",
                "sessionId": "astrodev-production-session",
                "sessionPath": str(session),
            })
            + "), publishEvidence:(handoff, deadlineAt)=>publishPrEvidence("
            + "handoff, { deadlineAt })});\n"
            + "await controller.createPr('--submit');\n"
        )
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        env = {
            **os.environ,
            "HOME": str(home),
            "ROOM_JSON": str(room),
            "TEAM_ROOM_TRUST_SERVER": "1",
            "TEAM_ROOM_TOKEN": "room-test-token",
            "ROOM_EVIDENCE_PRODUCER": "",
            "GITHUB_TOKEN": "",
            "GH_TOKEN": "",
            "GITHUB_PAT": "",
        }
        try:
            result = subprocess.run(
                [str(vite_node), str(runner)],
                cwd=package,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )
        finally:
            runner.unlink(missing_ok=True)
        assert result.returncode == 0, result.stdout + result.stderr
        artifact = json.loads(ContractServer.artifacts["artifact-1"]["raw"])
        chapter = artifact["chapters"][0]
        assert chapter["capture_fidelity"] == "partial"
        assert chapter["session_id"] == "astrodev-production-session"
        assert chapter["prompts"] == ["Fix production wrapper"]
        assert chapter["execution_spans"][0]["model"]["source"] == "unknown"
        assert any(
            event["type"] == "decision"
            and event["data"].get("omitted_bytes", 0) > 0
            for event in chapter["events"]
        )
        assert any(
            event["type"] == "agent_message"
            and event["summary"] == "Wrapper verified"
            for event in chapter["events"]
        )
        assert any(
            event["type"] == "tool_result"
            and event["summary"] == "1 passed"
            for event in chapter["events"]
        )
        assert "diff --git" in artifact["patch"]["text"]


def test_automatic_envelope_is_capped_one_shot_and_rejects_symlink_sessions():
    """Automatic capture accepts only one bounded header and an owned source file."""
    reset_contract_server()
    with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), ContractServer
    ) as srv:
        root = Path(td)
        repo, home, base, head = local_repo(root)
        endpoint = f"http://127.0.0.1:{srv.server_address[1]}"
        session = home / "session.jsonl"
        session.write_text(
            json.dumps(
                {
                    "type": "session",
                    "id": "secure-session",
                    "cwd": str(repo),
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "Private prompt"}],
                    },
                }
            )
            + "\n"
        )
        symlink = home / "session-link.jsonl"
        symlink.symlink_to(session)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        linked = run_automatic_astrodev_envelope(
            repo,
            home,
            endpoint,
            base,
            head,
            "secure-session",
            symlink,
        )
        assert linked.returncode == 0
        assert linked.stderr == b"room security refusal: unsafe PR evidence input\n"

        oversized = run_automatic_astrodev_envelope(
            repo,
            home,
            endpoint,
            base,
            head,
            "secure-session",
            session,
            envelope_override=(16 * 1024 + 1).to_bytes(4, "big"),
        )
        assert oversized.returncode == 0
        assert oversized.stderr == b""

        payload = {
            "pr_url": "https://github.com/owner/repository/pull/7",
            "base_ref": "main",
            "base_sha": base,
            "head_sha": head,
            "session_id": "secure-session",
            "session_cwd": str(repo),
            "session_path": str(session),
            "harness": "astrodev",
        }
        header = json.dumps(payload, separators=(",", ":")).encode()
        trailing = run_automatic_astrodev_envelope(
            repo,
            home,
            endpoint,
            base,
            head,
            "secure-session",
            session,
            envelope_override=(
                len(header).to_bytes(4, "big") + header + b"second-envelope"
            ),
        )
        assert trailing.returncode == 0
        assert trailing.stderr == b""
        assert ContractServer.artifacts == {}


def test_every_evidence_git_command_disables_promisor_lazy_fetch():
    """A promisor checkout cannot turn local evidence reads into GitHub traffic."""
    reset_contract_server()
    with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), ContractServer
    ) as srv:
        root = Path(td)
        repo, home, base, head = local_repo(root)
        producer(home / "producer.py")
        log = root / "git-env.log"
        fake_bin = root / "bin"
        fake_bin.mkdir()
        real_git = subprocess.check_output(["which", "git"], text=True).strip()
        shim = fake_bin / "git"
        shim.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"${{GIT_NO_LAZY_FETCH-unset}}\" >> {shlex.quote(str(log))}\n"
            f"exec {shlex.quote(real_git)} \"$@\"\n"
        )
        shim.chmod(0o700)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        result = run_publish(
            repo,
            home,
            f"http://127.0.0.1:{srv.server_address[1]}",
            base,
            head,
            "promisor-session",
            extra_env={"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        )
        assert result.returncode == 0 and "published" in result.stdout, (
            result.stdout + result.stderr
        )
        observed = log.read_text().splitlines()
        assert observed and set(observed) == {"1"}, observed


def test_pr_publish_is_nonblocking_without_room_configuration():
    home = Path(tempfile.mkdtemp())
    capture = home / "capture.jsonl"
    capture.write_text("private prompt and trajectory\n")
    capture.chmod(0o600)
    handoff = home / "handoff.json"
    handoff.write_text(json.dumps({
        "pr_url": "https://github.com/owner/repository/pull/7",
        "base_ref": "main",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "harness": "codex",
        "capture_path": str(capture),
    }))
    handoff.chmod(0o600)
    env = {
        **os.environ,
        "HOME": str(home),
        "ROOM_JSON": "",
        "TEAM_ROOM_HEALTH_LOG": str(home / "health.jsonl"),
    }
    result = subprocess.run(
        [sys.executable, str(KIT), "pr", "publish", "--handoff", str(handoff)],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "" and result.stderr == "", result.stdout + result.stderr
    assert not handoff.exists(), "private handoff must be consumed on every outcome"
    assert not capture.exists(), "private capture must be consumed on every outcome"
    rows = [
        json.loads(line)
        for line in (home / "health.jsonl").read_text().splitlines()
    ]
    assert any(row["component"] == "pr-evidence" for row in rows), rows
    print("PASS  unavailable automatic PR publication is quiet and self-cleaning")


def test_configured_pr_handoff_without_session_identity_is_quiet():
    reset_contract_server()
    with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), ContractServer
    ) as srv:
        root = Path(td)
        repo, home, base, head = local_repo(root)
        endpoint = f"http://127.0.0.1:{srv.server_address[1]}"
        room = home / "room.json"
        room.write_text(json.dumps({
            "thread_id": "thread-test",
            "team_id": "team-test",
            "server": endpoint,
            "portal": endpoint,
            "app_slug": "test",
            "publishable_key": "pk",
        }))
        handoff = home / "handoff.json"
        handoff.write_text(json.dumps({
            "pr_url": "https://github.com/owner/repository/pull/7",
            "base_ref": "main",
            "base_sha": base,
            "head_sha": head,
            "harness": "codex",
        }))
        handoff.chmod(0o600)
        env = {
            **os.environ,
            "HOME": str(home),
            "ROOM_JSON": str(room),
            "TEAM_ROOM_TRUST_SERVER": "1",
            "TEAM_ROOM_TOKEN": "room-test-token",
            "TEAM_ROOM_HEALTH_LOG": str(home / "health.jsonl"),
            "CODEX_THREAD_ID": "",
        }
        result = subprocess.run(
            [sys.executable, str(KIT), "pr", "publish", "--handoff", str(handoff)],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout == "" and result.stderr == "", result.stdout + result.stderr
        assert not handoff.exists()
        assert ContractServer.artifacts == {}
    print("PASS  configured missing session identity is quiet")


def test_untrusted_room_refusal_consumes_private_handoff_and_capture():
    home = Path(tempfile.mkdtemp())
    capture = home / "capture.jsonl"
    capture.write_text("private prompt and trajectory\n")
    capture.chmod(0o600)
    handoff = home / "handoff.json"
    handoff.write_text(json.dumps({
        "pr_url": "https://github.com/owner/repository/pull/7",
        "base_ref": "main",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "harness": "astrodev",
        "capture_path": str(capture),
    }))
    handoff.chmod(0o600)
    room = home / "room.json"
    room.write_text(json.dumps({
        "thread_id": "thread-test",
        "team_id": "team-test",
        "server": "https://untrusted.invalid",
        "portal": "https://untrusted.invalid",
        "app_slug": "test",
        "publishable_key": "pk",
    }))
    result = subprocess.run(
        [sys.executable, str(KIT), "pr", "publish", "--handoff", str(handoff)],
        env={
            **os.environ,
            "HOME": str(home),
            "ROOM_JSON": str(room),
            "TEAM_ROOM_TRUST_SERVER": "",
        },
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "REFUSING" in result.stderr
    assert not handoff.exists() and not capture.exists()
    print("PASS  untrusted destination refusal consumes private evidence files")


if __name__ == "__main__":
    test_two_agent_sessions_publish_one_current_artifact_over_tcp_without_github()
    test_concurrent_cold_starts_can_duplicate_artifacts_until_the_server_honors_the_create_key()
    test_real_cli_redacts_credentials_before_the_room_http_write()
    test_persisted_tcp_response_loss_recovers_each_logical_effect_once()
    test_pr_creation_handoff_runs_the_real_cli_without_github_credentials()
    test_astrodev_capture_runs_the_real_cli_without_generic_producer()
    test_issue_fixer_capture_keeps_both_real_codex_json_rounds()
    test_issue_fixer_production_wrapper_crosses_real_cli_and_adapter()
    test_astrodev_production_wrapper_crosses_real_cli_and_adapter()
    test_automatic_envelope_is_capped_one_shot_and_rejects_symlink_sessions()
    test_every_evidence_git_command_disables_promisor_lazy_fetch()
    test_pr_publish_is_nonblocking_without_room_configuration()
    test_configured_pr_handoff_without_session_identity_is_quiet()
    test_untrusted_room_refusal_consumes_private_handoff_and_capture()

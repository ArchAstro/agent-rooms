#!/usr/bin/env python3
"""Primary Room delivery is fast for the engineer and durable on ambiguity.

The canonical story crosses the real HTTP boundary: the server accepts the
first post but delays its response past the client's foreground budget. The
client returns promptly with a private queued entry. A later flush retries the
same idempotency key, the server observes one logical message, and the queue
drains.
"""

import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import socketserver
import sys
import tempfile
import threading
import time
import urllib.error
import subprocess


ROOT = Path(__file__).parents[1]
ROOM_POST = ROOT / "skills" / "team-room" / "room_post.py"


def load_room_post():
    spec = importlib.util.spec_from_file_location(
        f"room_post_primary_outbox_{time.time_ns()}", ROOM_POST
    )
    module = importlib.util.module_from_spec(spec)
    original_argv = sys.argv
    try:
        sys.argv = [str(ROOM_POST), "help"]
        spec.loader.exec_module(module)
    finally:
        sys.argv = original_argv
    return module


rp = load_room_post()


def reset_room_post():
    global rp
    rp = load_room_post()
    # Keep unit fixtures independent from this machine's installed Room.
    # CI has no room.json, while a developer laptop usually does; without a
    # test identity, otherwise-valid queue entries are classified as invalid
    # before the behavior under test can run.
    rp.PRODUCTION_SERVER = "https://room.example"
    rp.THREAD_ID = "thr_test"


class AmbiguousServer(http.server.BaseHTTPRequestHandler):
    logical_messages = {}
    attempts = []
    first_accepted = threading.Event()

    def do_GET(self):
        if self.path.endswith("/api/v1/users/me"):
            payload = {"id": "user", "app_id": "app"}
        elif "/threads/thr_test" in self.path:
            payload = {"members": [{"user": {
                "id": "user",
                "email": "outbox@example.test",
            }}]}
        else:
            self.send_error(404)
            return
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        size = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(size) or b"{}")
        key = body.get("idempotency_key")
        self.__class__.attempts.append(key)
        self.__class__.logical_messages.setdefault(key, body)
        if len(self.__class__.attempts) == 1:
            self.__class__.first_accepted.set()
            time.sleep(0.20)
        payload = json.dumps({"data": {"id": "msg_one"}}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except BrokenPipeError:
            pass

    def log_message(self, *_args):
        pass


def queue_entries(path):
    try:
        return [json.loads(line) for line in Path(path).read_text().splitlines() if line]
    except OSError:
        return []


def isolated_queue():
    temp = tempfile.mkdtemp()
    rp.PRIMARY_QUEUE_PATH = os.path.join(temp, "primary-outbox.jsonl")
    rp.PRIMARY_FLUSH_TOTAL_BUDGET_SECONDS = 2.0
    rp._spawn_primary_worker = lambda: None
    return rp.PRIMARY_QUEUE_PATH


def entry(message="queued", *, age=0, server=None, thread_id=None):
    return {
        "at": time.time() - age,
        "key": f"room-post:{message}",
        "server": server or rp.PRODUCTION_SERVER,
        "thread_id": thread_id or rp.THREAD_ID,
        "message": message,
        "metadata": None,
        "uploads": None,
    }


def test_a_timed_out_post_returns_quickly_and_later_delivers_exactly_once():
    AmbiguousServer.logical_messages = {}
    AmbiguousServer.attempts = []
    AmbiguousServer.first_accepted = threading.Event()
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), AmbiguousServer) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        server = f"http://127.0.0.1:{srv.server_address[1]}"
        home = tempfile.mkdtemp()
        config = {
            "thread_id": "thr_test",
            "team_id": "team_test",
            "server": server,
            "portal": server,
            "app_slug": "room",
            "publishable_key": "pk_test",
        }
        config_path = os.path.join(home, "room.json")
        Path(config_path).write_text(json.dumps(config))
        machine_config = Path(home, ".config", "team-room", "room.json")
        machine_config.parent.mkdir(parents=True)
        machine_config.write_text(json.dumps(config))
        Path(home, ".gitconfig").write_text(
            "[user]\n\temail = outbox@example.test\n\tname = Outbox Test\n"
        )
        env = dict(
            os.environ,
            HOME=home,
            ROOM_JSON=config_path,
            TEAM_ROOM_TRUST_SERVER="1",
            TEAM_ROOM_TOKEN="test-token",
            TEAM_ROOM_HEALTH_LOG=os.path.join(home, "health.jsonl"),
            TEAM_ROOM_PRIMARY_REQUEST_TIMEOUT="0.05",
            TEAM_ROOM_PRIMARY_TOTAL_BUDGET="2.0",
            TEAM_ROOM_PRIMARY_RETRY_DELAY="0.01",
        )

        # Real process boundary: the CLI appends and spawns a detached worker.
        # The server commits the first logical message but withholds its reply
        # past the worker's request budget, forcing an idempotent retry.
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(ROOM_POST), "done", "durable post", "--no-meta"],
            env=env,
            capture_output=True,
            text=True,
            timeout=2,
        )
        elapsed = time.monotonic() - started
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert elapsed < 0.5, elapsed
        assert AmbiguousServer.first_accepted.wait(1), "worker never reached server"
        outbox = Path(home, ".config", "team-room", "outbox")
        queue_paths = list(outbox.glob("*.jsonl"))
        assert len(queue_paths) == 1, queue_paths
        queue_path = str(queue_paths[0])
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if len(AmbiguousServer.attempts) >= 2 and not queue_entries(queue_path):
                break
            time.sleep(0.02)
        assert len(AmbiguousServer.attempts) == 2, AmbiguousServer.attempts
        key = AmbiguousServer.attempts[0]
        assert AmbiguousServer.attempts == [key, key]
        assert list(AmbiguousServer.logical_messages) == [key]
        assert queue_entries(queue_path) == []


def test_expired_and_corrupt_entries_cannot_wedge_the_outbox():
    reset_room_post()
    path = isolated_queue()
    delivered = []
    health = []
    rp._deliver_primary = lambda item, remaining: delivered.append(item["message"])
    rp.health_event = lambda category, reason: health.append((category, reason))
    Path(path).write_text(
        "not-json\n" + json.dumps(entry("ancient", age=8 * 86400)) + "\n"
    )
    os.chmod(path, 0o600)

    rp.primary_flush()

    assert delivered == [], delivered
    assert queue_entries(path) == []
    assert ("primary-outbox", "expired undelivered") in health


def test_an_entry_appended_during_delivery_is_not_stranded():
    reset_room_post()
    path = isolated_queue()
    delivered = []
    first = entry("first")
    second = entry("second")
    rp._primary_enqueue(first)

    def deliver(item, _remaining):
        delivered.append(item["message"])
        if item["message"] == "first":
            rp._primary_enqueue(second)

    rp._deliver_primary = deliver
    rp.health_event = lambda *_args: None
    rp.primary_flush()

    assert delivered == ["first", "second"], delivered
    assert queue_entries(path) == []


def test_detached_worker_command_survives_cli_preflight():
    reset_room_post()
    home = tempfile.mkdtemp()
    env = dict(
        os.environ,
        HOME=home,
        ROOM_JSON=str(ROOT / "tests" / "fixtures" / "room.json"),
        TEAM_ROOM_TRUST_SERVER="1",
        TEAM_ROOM_TOKEN="test-token",
        TEAM_ROOM_HEALTH_LOG=os.path.join(home, "health.jsonl"),
    )
    result = subprocess.run(
        [sys.executable, str(ROOM_POST), "primary-flush"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "usage:" not in (result.stdout + result.stderr).lower()


def test_rewrite_cannot_lose_an_appender_holding_the_old_inode():
    reset_room_post()
    path = isolated_queue()
    first = entry("first")
    second = entry("second")
    rp._primary_enqueue(first)
    consumed = Path(path).read_text().strip()

    real_open = rp.os.open
    real_replace = rp.os.replace
    appender_opened = threading.Event()
    let_appender_continue = threading.Event()
    replace_reached = threading.Event()
    appender_ident = {"value": None}

    def controlled_open(open_path, flags, *args, **kwargs):
        fd = real_open(open_path, flags, *args, **kwargs)
        if (
            threading.get_ident() == appender_ident["value"]
            and open_path == path
            and flags & os.O_APPEND
        ):
            appender_opened.set()
            assert let_appender_continue.wait(2)
        return fd

    def observed_replace(source, destination):
        replace_reached.set()
        let_appender_continue.set()
        return real_replace(source, destination)

    def append_second():
        appender_ident["value"] = threading.get_ident()
        rp._primary_enqueue(second)

    rp.os.open = controlled_open
    rp.os.replace = observed_replace
    append_thread = threading.Thread(target=append_second)
    rewrite_thread = threading.Thread(
        target=rp._primary_queue_rewrite, args=(consumed, None)
    )
    try:
        append_thread.start()
        assert appender_opened.wait(1)
        rewrite_thread.start()
        # With the fixed stable lock, rewrite cannot reach replace until the
        # appender finishes. Release it after proving that ordering. The old
        # implementation reaches replace first and releases it there.
        if not replace_reached.wait(0.15):
            let_appender_continue.set()
        append_thread.join(2)
        rewrite_thread.join(2)
    finally:
        let_appender_continue.set()
        rp.os.open = real_open
        rp.os.replace = real_replace
    assert not append_thread.is_alive() and not rewrite_thread.is_alive()
    assert [item["message"] for item in queue_entries(path)] == ["second"]


def test_flush_auth_and_post_share_one_request_budget():
    reset_room_post()
    observed = []
    rp._trusted_servers = lambda: {rp.PRODUCTION_SERVER}

    def slow_auth(timeout=None):
        observed.append(("auth", timeout))
        time.sleep(0.04)
        return None, None, None, {
            "accessToken": "token",
            "appId": "app",
            "userId": "user",
        }

    def slow_profile(*_args, **kwargs):
        observed.append(("profile", kwargs["timeout"]))
        time.sleep(0.05)
        return {"id": "user", "app_id": "app", "name": "User"}

    def record_post(*_args, **kwargs):
        observed.append(("post", kwargs["timeout"]))
        return {"id": "message"}

    rp.authed_session = slow_auth
    rp.http_get = slow_profile
    rp._post_once = record_post
    rp.PRIMARY_FLUSH_REQUEST_TIMEOUT = 1.0
    rp._deliver_primary(entry("budgeted"), 0.12)

    assert observed[0][0] == "auth" and 0 < observed[0][1] <= 0.12, observed
    assert observed[1][0] == "profile" and 0 < observed[1][1] < 0.09, observed
    assert observed[2][0] == "post" and 0 < observed[2][1] < 0.04, observed


def test_new_posts_cannot_overtake_an_existing_backlog():
    reset_room_post()
    path = isolated_queue()
    delivered = []
    rp._primary_enqueue(entry("old"))
    rp.authed_session = lambda timeout=None: (
        None, None, None, {"accessToken": "t", "appId": "a", "userId": "u"}
    )
    rp._post_once = lambda _session, message, *_args, **_kwargs: delivered.append(message) or {"id": "m"}
    rp._deliver_primary = lambda item, _remaining: delivered.append(item["message"])
    rp.health_event = lambda *_args: None

    rp.post("new", {"post_type": "done"})
    rp.primary_flush()

    assert delivered == ["old", "new"], delivered
    assert queue_entries(path) == []


def test_worker_retries_a_transient_failure_without_another_cli_invocation():
    reset_room_post()
    path = isolated_queue()
    attempts = []
    rp._primary_enqueue(entry("last-post"))
    rp.PRIMARY_FLUSH_TOTAL_BUDGET_SECONDS = 1.0
    rp.PRIMARY_RETRY_DELAY_SECONDS = 0.01
    rp.health_event = lambda *_args: None

    def flaky(item, _remaining):
        attempts.append(item["message"])
        if len(attempts) == 1:
            raise TimeoutError("transient")

    rp._deliver_primary = flaky
    rp.primary_flush()

    assert attempts == ["last-post", "last-post"], attempts
    assert queue_entries(path) == []


def test_valid_but_malformed_entries_are_removed_without_blocking_followers():
    reset_room_post()
    path = isolated_queue()
    delivered = []
    health = []
    Path(path).write_text(
        "[]\n"
        + json.dumps({"at": time.time(), "message": "missing identity"})
        + "\n"
        + json.dumps({**entry("bad binding"), "author_binding": "bad"})
        + "\n"
        + json.dumps({
            **entry("bad fingerprint"),
            "author_binding": {"kind": "static", "credential_sha256": "tiny"},
        })
        + "\n"
        + json.dumps(entry("valid"))
        + "\n"
    )
    os.chmod(path, 0o600)
    rp._deliver_primary = lambda item, _remaining: delivered.append(item["message"])
    rp.health_event = lambda category, reason: health.append((category, reason))

    rp.primary_flush()

    assert delivered == ["valid"], delivered
    assert queue_entries(path) == []
    assert sum(reason == "invalid entry" for _category, reason in health) == 4


def test_enqueue_repairs_existing_queue_permissions():
    reset_room_post()
    path = isolated_queue()
    Path(path).write_text("")
    os.chmod(path, 0o644)

    assert rp._primary_enqueue(entry("private")) is True

    assert os.stat(path).st_mode & 0o777 == 0o600


def test_failed_enqueue_does_not_advance_exhaust_or_mirror():
    reset_room_post()
    advanced = []
    mirrored = []
    original_argv = list(sys.argv)
    rp.post = lambda *_args, **_kwargs: False
    rp._advance_room_marker = lambda: advanced.append(True)
    rp.mention_peek = lambda: None
    rp.record_session = lambda *_args, **_kwargs: None
    rp.session_nudge = lambda *_args, **_kwargs: ""
    rp.mirror_fanout = lambda *_args, **_kwargs: mirrored.append(True)
    try:
        sys.argv = ["room-post", "done", "meaningful outcome", "--no-meta"]
        rp.main()
    finally:
        sys.argv = original_argv

    assert advanced == [] and mirrored == [], (advanced, mirrored)


def test_worker_falls_back_from_rejected_courier_to_human_login():
    reset_room_post()
    rp._trusted_servers = lambda: {rp.PRODUCTION_SERVER}
    courier = {
        "accessToken": "courier",
        "appId": "app",
        "userId": "courier-user",
        "static": True,
    }
    human = {"accessToken": "human", "appId": "app", "userId": "human-user"}
    rp.authed_session = lambda timeout=None: (None, None, None, courier)
    rp.login_session = lambda timeout=None: ({}, "key", "path", human)
    attempts = []

    def reject_courier(session, *_args, **_kwargs):
        attempts.append(session["accessToken"])
        if session["accessToken"] == "courier":
            raise urllib.error.HTTPError("https://room.example", 403, "denied", {}, None)
        return {"id": "landed"}

    rp._post_once = reject_courier

    rp._deliver_primary(entry("auth fallback"), 0.5)

    assert attempts == ["courier", "human"], attempts


def test_new_static_posts_cannot_change_author_during_durable_delivery():
    reset_room_post()
    path = isolated_queue()
    rp._trusted_servers = lambda: {rp.PRODUCTION_SERVER}
    previous = os.environ.get("TEAM_ROOM_TOKEN")
    try:
        os.environ["TEAM_ROOM_TOKEN"] = "token-owner-a"
        assert rp.post("bound author") is True
        queued = queue_entries(path)
        assert len(queued) == 1, queued
        binding = queued[0].get("author_binding")
        assert binding == {
            "kind": "static",
            "credential_sha256": hashlib.sha256(
                b"token-owner-a"
            ).hexdigest(),
        }, binding
        assert "token-owner-a" not in Path(path).read_text()

        # A later shell may carry a different named token. The durable entry
        # must wait for its original credential instead of silently changing
        # the platform author.
        os.environ["TEAM_ROOM_TOKEN"] = "token-owner-b"
        delivered = []
        rp._post_once = lambda *_args, **_kwargs: delivered.append(True)
        try:
            rp._deliver_primary(queued[0], 0.5)
        except RuntimeError as exc:
            assert "credential changed" in str(exc), exc
        else:
            raise AssertionError("a different token delivered the queued post")
        assert delivered == []
    finally:
        if previous is None:
            os.environ.pop("TEAM_ROOM_TOKEN", None)
        else:
            os.environ["TEAM_ROOM_TOKEN"] = previous


def test_new_browser_posts_cannot_change_author_after_relogin():
    reset_room_post()
    path = isolated_queue()
    rp._trusted_servers = lambda: {rp.PRODUCTION_SERVER}
    temp = tempfile.mkdtemp()
    rp.ROOM_CREDS_PATH = os.path.join(temp, "credentials.json")
    Path(rp.ROOM_CREDS_PATH).write_text(json.dumps({
        "server": rp.PRODUCTION_SERVER,
        "orgSessions": {"app": {
            "accessToken": "browser-a",
            "refreshToken": "refresh-a",
            "expiresAt": int((time.time() + 3600) * 1000),
            "appId": "app",
            "userId": "user-a",
        }},
    }))
    previous = os.environ.pop("TEAM_ROOM_TOKEN", None)
    try:
        assert rp.post("browser-bound author") is True
        queued = queue_entries(path)
        assert queued[0].get("author_binding") == {
            "kind": "browser",
            "user_id": "user-a",
        }, queued
        rp.login_session = lambda timeout=None: (
            {},
            "app",
            rp.ROOM_CREDS_PATH,
            {
                "accessToken": "browser-b",
                "appId": "app",
                "userId": "user-b",
            },
        )
        delivered = []
        rp._post_once = lambda *_args, **_kwargs: delivered.append(True)
        try:
            rp._deliver_primary(queued[0], 0.5)
        except RuntimeError as exc:
            assert "credential changed" in str(exc), exc
        else:
            raise AssertionError("a different login delivered the queued post")
        assert delivered == []
    finally:
        if previous is not None:
            os.environ["TEAM_ROOM_TOKEN"] = previous


def test_browser_delivery_replaces_git_author_metadata_with_platform_profile():
    reset_room_post()
    session = {
        "accessToken": "browser-token",
        "appId": "app",
        "userId": "user-platform",
    }
    rp.http_get = lambda *_args, **_kwargs: {
        "id": "user-platform",
        "app_id": "app",
        "name": "Platform Person",
    }

    metadata = rp._platform_author_metadata(
        session,
        {"post_type": "done", "human": "Wrong Git Name"},
        timeout=0.5,
    )

    assert metadata["human"] == "Platform Person", metadata
    assert metadata["author_user_id"] == "user-platform", metadata
    assert session["principalName"] == "Platform Person", session


def test_browser_delivery_rejects_a_profile_that_disagrees_with_the_session():
    reset_room_post()
    session = {
        "accessToken": "browser-token",
        "appId": "app",
        "userId": "stored-user",
    }
    rp.http_get = lambda *_args, **_kwargs: {
        "id": "token-owner",
        "app_id": "app",
        "name": "Token Owner",
    }

    try:
        rp._platform_author_metadata(
            session,
            {"post_type": "done", "human": "Stored User"},
            timeout=0.5,
        )
    except RuntimeError as exc:
        assert "does not match" in str(exc), exc
    else:
        raise AssertionError("a mismatched token and stored user were accepted")


def test_primary_outboxes_and_credentials_are_bound_to_one_room():
    reset_room_post()
    outbox_dir = tempfile.mkdtemp()
    rp.PRIMARY_OUTBOX_DIR = outbox_dir
    room_a_path = rp.primary_queue_path("https://a.example", "thr_a")
    room_b_path = rp.primary_queue_path("https://b.example", "thr_b")
    assert room_a_path != room_b_path

    # A worker running with room B's configuration must neither discover room
    # A's backlog nor authenticate before rejecting an A entry handed to it.
    rp.PRODUCTION_SERVER = "https://b.example"
    rp.THREAD_ID = "thr_b"
    rp._trusted_servers = lambda: {"https://b.example"}
    rp.PRIMARY_QUEUE_PATH = room_b_path
    auth_calls = []
    rp.authed_session = lambda timeout=None: auth_calls.append(timeout)
    try:
        rp._deliver_primary(
            entry("room A", server="https://a.example", thread_id="thr_a"), 0.5
        )
    except ValueError as exc:
        assert "worker context" in str(exc)
    else:
        raise AssertionError("cross-room primary entry was accepted")
    assert auth_calls == []


def test_invalid_worker_budget_environment_cannot_break_the_cli():
    home = tempfile.mkdtemp()
    env = dict(
        os.environ,
        HOME=home,
        ROOM_JSON=str(ROOT / "tests" / "fixtures" / "room.json"),
        TEAM_ROOM_TRUST_SERVER="1",
        TEAM_ROOM_PRIMARY_REQUEST_TIMEOUT="not-a-number",
        TEAM_ROOM_PRIMARY_TOTAL_BUDGET="-1",
        TEAM_ROOM_PRIMARY_RETRY_DELAY="nan",
    )
    result = subprocess.run(
        [sys.executable, str(ROOM_POST), "help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_permanently_invalid_payload_cannot_block_later_room_posts():
    reset_room_post()
    path = isolated_queue()
    delivered = []
    health = []
    rp._primary_enqueue(entry("invalid"))
    rp._primary_enqueue(entry("valid"))

    def deliver(item, _remaining):
        if item["message"] == "invalid":
            raise urllib.error.HTTPError(
                "https://room.example", 422, "invalid payload", {}, None
            )
        delivered.append(item["message"])

    rp._deliver_primary = deliver
    rp.health_event = lambda category, reason: health.append((category, reason))
    rp.primary_flush()

    assert delivered == ["valid"], delivered
    assert queue_entries(path) == []
    assert ("primary-outbox", "discarded HTTP 422") in health


def test_append_at_worker_shutdown_is_observed_or_spawns_a_successor():
    reset_room_post()
    path = isolated_queue()
    delivered = []
    spawned = []
    rp._primary_enqueue(entry("first"))
    rp._deliver_primary = lambda item, _remaining: delivered.append(item["message"])
    def spawn_if_worker_idle():
        import fcntl
        probe = open(path + ".lock", "w")
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        finally:
            probe.close()
        spawned.append(True)

    rp._spawn_primary_worker = spawn_if_worker_idle
    rp.health_event = lambda *_args: None

    real_read = rp._primary_queue_read
    reads = {"count": 0}
    observed_empty = threading.Event()
    poster_done = threading.Event()

    def controlled_read():
        reads["count"] += 1
        result = real_read()
        if reads["count"] == 2 and result == []:
            observed_empty.set()
            assert poster_done.wait(2)
        return result

    rp._primary_queue_read = controlled_read
    worker = threading.Thread(target=rp.primary_flush)
    worker.start()
    assert observed_empty.wait(2)
    rp._primary_enqueue(entry("second"))
    poster_done.set()
    worker.join(2)

    assert not worker.is_alive()
    assert delivered == ["first", "second"], (delivered, spawned)
    assert queue_entries(path) == []


def test_worker_never_sends_a_browser_credential_to_another_server():
    reset_room_post()
    temp = tempfile.mkdtemp()
    rp.PRODUCTION_SERVER = "https://b.example"
    rp.THREAD_ID = "thr_b"
    rp._trusted_servers = lambda: {"https://b.example"}
    rp.ROOM_CREDS_PATH = os.path.join(temp, "credentials.json")
    Path(rp.ROOM_CREDS_PATH).write_text(json.dumps({
        "server": "https://a.example",
        "orgSessions": {"app_a": {
            "accessToken": "TOKEN_A",
            "refreshToken": "refresh-a",
            "expiresAt": int((time.time() + 3600) * 1000),
            "appId": "app_a",
            "userId": "user_a",
        }},
    }))
    sent = []
    rp._post_once = lambda session, *_args, **_kwargs: sent.append(session)
    try:
        rp._deliver_primary(
            entry("room B", server="https://b.example", thread_id="thr_b"), 0.5
        )
    except SystemExit:
        pass
    assert sent == []


def test_unscoped_global_token_file_is_always_ignored():
    reset_room_post()
    temp = tempfile.mkdtemp()
    rp.PRODUCTION_SERVER = "https://b.example"
    rp.THREAD_ID = "thr_b"
    rp.ROOM_TOKEN_PATH = os.path.join(temp, "token")
    rp.ROOM_CONFIG_PATH = os.path.join(temp, "room.json")
    Path(rp.ROOM_TOKEN_PATH).write_text("TOKEN_A")
    Path(rp.ROOM_CONFIG_PATH).write_text(json.dumps({
        "server": "https://a.example",
        "thread_id": "thr_a",
    }))
    previous = os.environ.pop("TEAM_ROOM_TOKEN", None)
    try:
        assert rp.static_token() is None
        Path(rp.ROOM_CONFIG_PATH).write_text(json.dumps({
            "server": "https://b.example",
            "thread_id": "thr_b",
        }))
        assert rp.static_token() is None
    finally:
        if previous is not None:
            os.environ["TEAM_ROOM_TOKEN"] = previous


if __name__ == "__main__":
    test_a_timed_out_post_returns_quickly_and_later_delivers_exactly_once()
    test_expired_and_corrupt_entries_cannot_wedge_the_outbox()
    test_an_entry_appended_during_delivery_is_not_stranded()
    test_detached_worker_command_survives_cli_preflight()
    test_rewrite_cannot_lose_an_appender_holding_the_old_inode()
    test_flush_auth_and_post_share_one_request_budget()
    test_new_posts_cannot_overtake_an_existing_backlog()
    test_worker_retries_a_transient_failure_without_another_cli_invocation()
    test_valid_but_malformed_entries_are_removed_without_blocking_followers()
    test_enqueue_repairs_existing_queue_permissions()
    test_failed_enqueue_does_not_advance_exhaust_or_mirror()
    test_worker_falls_back_from_rejected_courier_to_human_login()
    test_new_static_posts_cannot_change_author_during_durable_delivery()
    test_new_browser_posts_cannot_change_author_after_relogin()
    test_browser_delivery_replaces_git_author_metadata_with_platform_profile()
    test_browser_delivery_rejects_a_profile_that_disagrees_with_the_session()
    test_primary_outboxes_and_credentials_are_bound_to_one_room()
    test_invalid_worker_budget_environment_cannot_break_the_cli()
    test_permanently_invalid_payload_cannot_block_later_room_posts()
    test_append_at_worker_shutdown_is_observed_or_spawns_a_successor()
    test_worker_never_sends_a_browser_credential_to_another_server()
    test_unscoped_global_token_file_is_always_ignored()
    print("PASS  timed-out primary post is retried exactly once logically")
    print("PASS  corrupt and expired primary entries are removed")
    print("PASS  primary appends during drain are not stranded")
    print("PASS  detached primary worker survives CLI preflight")
    print("PASS  stable queue lock preserves concurrent append")
    print("PASS  primary flush auth and post share one budget")
    print("PASS  primary posts preserve global FIFO order")
    print("PASS  detached worker owns transient retry")
    print("PASS  malformed entries cannot head-of-line block")
    print("PASS  primary queue permissions self-heal")
    print("PASS  failed enqueue preserves exhaust and mirror state")
    print("PASS  primary worker falls back to human login")
    print("PASS  new primary entries cannot change authors across retries")
    print("PASS  primary outboxes and credentials are room-bound")
    print("PASS  invalid worker budgets fall back safely")
    print("PASS  permanently invalid payloads cannot block later posts")
    print("PASS  worker shutdown cannot strand a concurrent append")
    print("PASS  browser credentials never cross server boundaries")
    print("PASS  unscoped global token files always fail closed")

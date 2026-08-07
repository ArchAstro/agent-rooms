#!/usr/bin/env python3
"""Contract suite: the kit against a hermetic in-process server that speaks
the developer API's EXACT shapes — every one of these assertions encodes a
shape that broke us in production first.

    python3 tests/test_contract.py

Runs in-process (stdlib http.server), no network, whole suite in seconds —
sized for the CI budget (agent-rooms CI must stay under ~2 minutes). The
same assertions are the future `doctor --contract` probe against live
environments; this file is the local half.
"""
import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "skills", "team-room", "room_post.py")

CALLS = []


class Stub(http.server.BaseHTTPRequestHandler):
    """The developer API, distilled to the shapes the kit depends on."""

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        CALLS.append(("GET", self.path))
        if "/context/sources/" in self.path and self.path.endswith("/search"):
            self._json(200, {"data": []})
        elif "/custom_objects" in self.path:
            # CONTRACT: paged with has_next; page param honored (records
            # fetch loops until has_next false — an infinite-loop trap if
            # the server shape changes)
            page = "page=2" in self.path
            self._json(200, {"data": [] if page else [
                {"id": "obj1", "fields": {"record_id": "r1", "status": "approved",
                                          "kind": "rule", "title": "t"}}],
                "has_next": not page})
        elif "/messages" in self.path:
            # CONTRACT: list honors `limit`, returns {data:[...]} with
            # sender_name/content/created_at; metadata is NOT serialized
            # here (the kit must never depend on it in REST lists)
            q = self.path.split("?")[-1]
            n = 3 if "limit=15" in q or "page_size=15" in q else 1
            self._json(200, {"data": [
                {"id": f"m{i}", "sender_name": "Rob Masson",
                 "content": "@vivek please look at the deploy",
                 "created_at": "2026-07-26T15:00:00"} for i in range(n)]})
        elif "/users/me" in self.path:
            self._json(200, {"app_id": "app_stub"})
        elif "/threads/thr_stub" in self.path and "/messages" not in self.path:
            # CONTRACT: identity resolution matches a member by git email
            self._json(200, {"members": [
                {"user": {"id": "usr_stub", "email": "contract@stub.test",
                          "full_name": "Stub User"}}]})
        else:
            self._json(404, {"error": {"code": "not_found"}})

    def do_POST(self):
        CALLS.append(("POST", self.path))
        ln = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(ln) or b"{}")
        if self.path.endswith("/search"):
            self._json(200, {"data": [
                {"id": "hit1", "content": "⚠ lesson content",
                 "metadata": {"post_type": "lesson", "human": "Rob"}}]})
        elif self.path.endswith("/messages"):
            # CONTRACT: post accepts content+metadata, returns {data:{id}};
            # the kit's metadata must ride through intact
            assert body.get("content"), "post without content"
            self._json(200, {"data": {"id": "msg_stub_1"}})
        elif "/auth/refresh" in self.path:
            # CONTRACT: refresh tokens ROTATE — the kit must persist the
            # NEW refresh token or the next refresh dies
            self._json(200, {"access_token": "at2", "refresh_token": "rt2",
                             "expires_at": 9999999999999})
        else:
            self._json(404, {"error": {"code": "not_found"}})

    def log_message(self, *a):
        pass


def run_kit(args, home, server, extra_env=None):
    cfg = {"thread_id": "thr_stub", "team_id": "tem_stub", "server": server,
           "portal": server, "app_slug": "stub", "publishable_key": "pk",
           "source_id": "src_stub"}
    cfg_path = os.path.join(home, "room.json")
    json.dump(cfg, open(cfg_path, "w"))
    env = dict(os.environ)
    env.update({"HOME": home, "ROOM_JSON": cfg_path,
                "TEAM_ROOM_TRUST_SERVER": "1",
                "TEAM_ROOM_TOKEN": "static-stub-token",
                "TEAM_ROOM_HEALTH_LOG": os.path.join(home, "health.jsonl")})
    # The sandbox HOME needs a git identity matching the stub's member —
    # identity resolution matches members by the machine's git email.
    with open(os.path.join(home, ".gitconfig"), "w") as f:
        f.write("[user]\n\temail = contract@stub.test\n\tname = Stub User\n")
    env.update(extra_env or {})
    return subprocess.run([sys.executable, KIT, *args], env=env,
                          capture_output=True, text=True, timeout=60)


def wait_for_post(after, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(method == "POST" and path.endswith("/messages")
               for method, path in CALLS[after:]):
            return
        time.sleep(0.01)
    raise AssertionError(f"detached worker did not post: {CALLS[after:]}")


def main():
    with socketserver.TCPServer(("127.0.0.1", 0), Stub) as srv:
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        server = f"http://127.0.0.1:{port}"
        home = tempfile.mkdtemp()

        # 1. a post returns silently after durable enqueue, then lands through
        # the detached worker without occupying the engineer's foreground.
        help_result = run_kit(["--help"], home, server)
        assert "bounded evidence package" in help_result.stdout and "room-post pr publish" in help_result.stdout, help_result.stdout
        assert "room-post pr review" not in help_result.stdout, help_result.stdout
        assert "editable routine" not in help_result.stdout, help_result.stdout
        print("PASS  help documents bounded PR evidence publication")

        # Local argument handling must never touch the Room or masquerade as a
        # knowledge outage. Nested help is especially important for agents:
        # `done --help` must not publish a post whose headline is "--help".
        for nested in (
            ["read", "--help"],
            ["search", "--help"],
            ["brief", "--help"],
            ["records", "--help"],
            ["records", "show", "--help"],
            ["inbox", "--help"],
            ["doctor", "--help"],
            ["login", "--help"],
            ["pr", "publish", "--help"],
            ["done", "--help"],
        ):
            before = list(CALLS)
            result = run_kit(nested, home, server)
            assert result.returncode == 0, (nested, result.stdout, result.stderr)
            assert "usage:" in result.stdout.lower(), (nested, result.stdout, result.stderr)
            assert "unavailable" not in (result.stdout + result.stderr).lower(), (
                nested,
                result.stdout,
                result.stderr,
            )
            assert CALLS == before, (nested, CALLS[len(before):])
        print("PASS  nested help is local, offline, and side-effect free")

        for invalid in (
            ["read", "many"],
            ["read", "1", "extra"],
            ["search"],
            ["search", "query", "extra"],
            ["brief", "extra"],
            ["records", "--status"],
            ["inbox", "extra"],
            ["doctor", "extra"],
            ["discover", "--team"],
            ["init", "--config"],
            ["login", "staging", "extra"],
            ["pr", "review"],
            ["pr", "publish", "--bogus"],
            ["pr", "publish", "7"],
            ["pr", "publish", "7", "--base-sha", "a", "--head-sha"],
            ["pr", "publish", "7", "--base-sha", "a", "--head-sha", "b",
             "--from-artifact-version", "many"],
            ["pr", "publish", "7", "--base-sha", "a", "--head-sha", "b",
             "--mode", "surprise"],
            ["pr", "publish", "7", "--base-sha", "a", "--head-sha", "b",
             "--harness", "surprise"],
            ["pr", "publish", "7", "--base-sha", "a", "--head-sha", "b",
             "--pr-url", "https://example.invalid/pull/7"],
            ["pr", "publish", "7", "--base-sha", "a", "--head-sha", "b",
             "--agent-type", "coding-agent"],
            ["pr", "publish", "7", "--base-sha", "a", "--head-sha", "b",
             "--model", "some-model"],
            ["done"],
            ["done", ""],
            ["done", "--dry-run"],
            ["done", "A useful headline", "-b"],
            ["done", "A useful headline", "--bogus"],
            ["notify", "A useful headline"],
            ["done", "x" * 301],
            ["frobnicate"],
        ):
            before = list(CALLS)
            result = run_kit(invalid, home, server)
            assert result.returncode == 2, (invalid, result.stdout, result.stderr)
            output = result.stdout + result.stderr
            assert "usage:" in output.lower(), (invalid, output)
            assert "unavailable" not in output.lower(), (invalid, output)
            assert CALLS == before, (invalid, CALLS[len(before):])
        print("PASS  local usage errors are precise and never reported as outages")

        offline = tempfile.mkdtemp()
        offline_env = {
            **os.environ,
            "HOME": offline,
            "ROOM_JSON": "",
            "TEAM_ROOM_HEALTH_LOG": os.path.join(offline, "health.jsonl"),
        }
        for argv, expected_code in (
            ([], 0),
            (["read", "--help"], 0),
            (["done", "--help"], 0),
            (["read", "many"], 2),
            (["frobnicate"], 2),
        ):
            result = subprocess.run(
                [sys.executable, KIT, *argv],
                env=offline_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == expected_code, (argv, result.stderr)
            output = result.stdout + result.stderr
            if argv:
                assert "usage:" in output.lower(), (argv, output)
            else:
                assert "room-post" in output.lower(), (argv, output)
            assert "unavailable" not in output.lower(), (argv, output)
        assert not os.path.exists(offline_env["TEAM_ROOM_HEALTH_LOG"])
        print("PASS  local help and usage validation work before Room configuration")

        discover = subprocess.run(
            [sys.executable, KIT, "discover"],
            env=offline_env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert discover.returncode == 3, discover.stdout + discover.stderr
        assert "sign in first" in discover.stderr.lower(), discover.stderr
        assert "unavailable" not in (discover.stdout + discover.stderr).lower()
        print("PASS  explicit discovery gives an actionable authentication result")

        refused_env = {
            **offline_env,
            "TEAM_ROOM_TOKEN": "token",
            "ROOM_SERVER": "http://127.0.0.1:1",
        }
        discover = subprocess.run(
            [sys.executable, KIT, "discover"],
            env=refused_env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert discover.returncode == 3, discover.stdout + discover.stderr
        output = discover.stdout + discover.stderr
        assert "room discovery unavailable" in output.lower(), output
        assert "no team room found" not in output.lower(), output
        print("PASS  failed discovery is never mislabeled as no room membership")

        broken_config = os.path.join(offline, "broken-room.json")
        with open(broken_config, "w") as handle:
            handle.write("{not-json")
        broken_env = {**offline_env, "ROOM_JSON": broken_config}
        result = subprocess.run(
            [sys.executable, KIT, "--help"],
            env=broken_env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "room-post" in result.stdout and result.stderr == "", (
            result.stdout,
            result.stderr,
        )
        print("PASS  top-level help ignores broken Room configuration")

        replacement_config = os.path.join(offline, "replacement-room.json")
        with open(replacement_config, "w") as handle:
            json.dump({
                "thread_id": "thread",
                "team_id": "team",
                "server": "https://example.invalid",
                "portal": "https://example.invalid",
                "app_slug": "room",
                "publishable_key": "pk",
            }, handle)
        result = subprocess.run(
            [sys.executable, KIT, "init", "--config", replacement_config],
            env=broken_env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "room identity saved" in result.stdout, result.stdout + result.stderr
        print("PASS  init can repair a broken existing Room configuration")

        result = subprocess.run(
            [sys.executable, KIT, "done", "Local preview", "--dry-run"],
            env=offline_env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Local preview" in result.stdout, result.stdout + result.stderr
        assert "unavailable" not in (result.stdout + result.stderr).lower()
        assert not os.path.exists(offline_env["TEAM_ROOM_HEALTH_LOG"])
        print("PASS  dry-run is a fully local preview")

        before = list(CALLS)
        result = run_kit(
            ["done", "Real post headline", "-b", "--dry-run"],
            home,
            server,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        deadline = threading.Event()
        for _ in range(100):
            if any(
                method == "POST" and path.endswith("/messages")
                for method, path in CALLS[len(before):]
            ):
                break
            deadline.wait(0.01)
        assert any(
            method == "POST" and path.endswith("/messages")
            for method, path in CALLS[len(before):]
        ), CALLS[len(before):]
        print("PASS  dry-run text used as data cannot suppress queued delivery")

        missing_attachment = os.path.join(offline, "does-not-exist.png")
        result = subprocess.run(
            [sys.executable, KIT, "done", "A useful headline", "-a", missing_attachment],
            env=offline_env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        output = result.stdout + result.stderr
        assert "can't read attachment" in output.lower(), output
        assert "unavailable" not in output.lower(), output
        assert not os.path.exists(offline_env["TEAM_ROOM_HEALTH_LOG"])
        print("PASS  local attachment errors do not become Room failures")

        calls_before_review = list(CALLS)
        review_result = run_kit(
            ["pr", "review", "artifact", "--version", "1", "--head-sha", "a" * 40],
            home,
            server,
        )
        # Removed subcommands are local usage errors, not Room failures. They
        # are rejected before configuration or any API request.
        assert review_result.returncode == 2
        assert "usage: room-post pr publish" in review_result.stderr, review_result.stderr
        assert "unavailable" not in review_result.stderr.lower()
        assert CALLS == calls_before_review, CALLS
        print("PASS  deferred PR review command is unavailable")

        before = list(CALLS)
        missing_record = run_kit(["records", "show", "missing-record"], home, server)
        assert missing_record.returncode == 0, (
            missing_record.stdout,
            missing_record.stderr,
        )
        output = missing_record.stdout + missing_record.stderr
        assert "no record 'missing-record'" in output, output
        assert "unavailable" not in output.lower(), output
        assert not any(
            method == "POST" for method, _path in CALLS[len(before):]
        ), CALLS[len(before):]
        print("PASS  a missing record is not mislabeled as a Room outage")

        before_post = len(CALLS)
        r = run_kit(["done", "contract post", "-r", "#1"], home, server)
        assert r.returncode == 0
        assert r.stdout == "", r.stdout
        assert r.stderr == "", r.stderr
        wait_for_post(before_post)
        print("PASS  post queues silently and detached worker delivers")

        # 2. records pagination follows has_next and terminates
        r = run_kit(["records"], home, server)
        assert "r1" in r.stdout, r.stdout + r.stderr
        pages = [p for m, p in CALLS if "custom_objects" in p]
        assert any("page=2" in p for p in pages), "did not follow has_next"
        print("PASS  records pagination terminates via has_next")

        # 3. search renders stub hits without crashing on minimal shapes
        r = run_kit(["search", "anything"], home, server)
        assert "lesson" in r.stdout, r.stdout + r.stderr
        print("PASS  search renders hits")

        r = run_kit(["search", "help"], home, server)
        assert "lesson" in r.stdout and "usage:" not in r.stdout.lower(), r.stdout
        before_post = len(CALLS)
        r = run_kit(["done", "help", "-r", "#2"], home, server)
        assert r.returncode == 0 and r.stdout == "", r.stdout + r.stderr
        wait_for_post(before_post)
        before_post = len(CALLS)
        r = run_kit(
            ["done", "Help text is valid post data", "-b", "--help", "-r", "#3"],
            home,
            server,
        )
        assert r.returncode == 0 and r.stdout == "", r.stdout + r.stderr
        wait_for_post(before_post)
        print("PASS  bare help remains valid command data")

        r = run_kit(["read", "1"], home, server)
        assert "--- m0" in r.stdout, r.stdout + r.stderr
        assert "re-read" not in r.stdout and "SKILL.md" not in r.stdout, r.stdout
        print("PASS  read returns team activity without maintenance prompts")

        # 4. brief with approved records
        r = run_kit(["brief"], home, server)
        assert "TEAM RECORDS" in r.stdout or "r1" in r.stdout, r.stdout
        print("PASS  brief reads records")

        # 5. every request carries the version header (fleet telemetry)
        # (stub can't inspect UA per-call easily here; presence is pinned by
        # unit tests — this suite pins shapes. Skipping duplicate.)

        # 6. the guard: an untrusted server in ROOM_JSON refuses before auth
        r = run_kit(["search", "x"], home, "https://evil.contract.example",
                    extra_env={"TEAM_ROOM_TRUST_SERVER": ""})
        assert "REFUSING" in r.stderr, r.stderr
        print("PASS  untrusted server refused")

        disconnected = tempfile.mkdtemp()
        r = subprocess.run(
            [sys.executable, KIT, "done", "Finished the requested work"],
            env={**os.environ, "HOME": disconnected, "ROOM_JSON": "",
                 "TEAM_ROOM_HEALTH_LOG": os.path.join(disconnected, "health.jsonl")},
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0 and r.stdout == "" and r.stderr == "", r.stdout + r.stderr
        r = subprocess.run(
            [sys.executable, KIT, "search", "relevant subsystem"],
            env={**os.environ, "HOME": disconnected, "ROOM_JSON": "",
                 "TEAM_ROOM_HEALTH_LOG": os.path.join(disconnected, "health.jsonl")},
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 0 and r.stdout == "room-status: login-required\n" and r.stderr == "", r.stdout + r.stderr
        print("PASS  a fresh install requests one-time login without blocking")

    print("OK contract")


if __name__ == "__main__":
    main()

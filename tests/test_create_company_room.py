#!/usr/bin/env python3
"""The first person at a company can make its room themselves.

    python3 tests/test_create_company_room.py

The wall this removes: `init` only writes a config somebody hands you and
`discover` only finds a room that already exists, so person one had nowhere
to get a room from and asked us for three ids over Slack. Everyone after
them was already fine — signing in joins you to your company's room.

What the room has to come out with, or it is quietly broken:

  * a read grant for the company, which is the only reason a colleague can
    see it at all, and
  * a label saying it is that company's room, which is how they tell it
    apart from every other team they could join,

which together are exactly what the join path keys on. Plus the room's
conversation and its three schemas, without which records, pins and the
presence strip fail later rather than now.

Runs in-process against a stub of the API, no network.
"""
import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "skills", "team-room", "room_post.py")

CALLS = []
MY_ORG = "org_mine"
ROOM_LABEL = "archastro_team_room"


class Stub(http.server.BaseHTTPRequestHandler):
    """The API, reduced to what creating a room touches."""

    teams = []          # rows the discovery query can return
    created = []        # POST /teams bodies
    threads = []        # POST /teams/:id/threads bodies
    schemas = []        # POST /config bodies
    team_post_status = None
    schema_status = None

    def log_message(self, *a):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        CALLS.append(("GET", self.path))
        if self.path.startswith("/api/v1/users/me"):
            self._json(200, {"id": "usr_me", "org": MY_ORG})
        elif self.path.startswith("/api/v1/teams/"):
            # A single team, with its conversations — how the kit confirms a
            # labelled team really is a room.
            tid = self.path.split("/api/v1/teams/")[1].split("?")[0]
            row = next((t for t in Stub.teams if t["id"] == tid), None)
            self._json(200, row or {})
        elif self.path.startswith("/api/v1/teams"):
            # Discovery. Only rows the test planted; membership filters are
            # irrelevant here because the point is what happens when the
            # company has nothing.
            self._json(200, {"data": list(Stub.teams), "has_next": False})
        else:
            self._json(200, {})

    def do_POST(self):
        CALLS.append(("POST", self.path))
        body = self._body()
        if self.path == "/api/v1/teams":
            if Stub.team_post_status:
                self._json(Stub.team_post_status, {"error": "nope"})
                return
            Stub.created.append(body)
            self._json(200, {"id": "tem_new"})
        elif self.path.endswith("/threads"):
            Stub.threads.append({"path": self.path, "body": body})
            self._json(200, {"id": "thr_new"})
        elif self.path == "/api/v1/config":
            if Stub.schema_status:
                self._json(Stub.schema_status, {"error": "nope"})
                return
            Stub.schemas.append(body)
            self._json(200, {"id": "cfg_new"})
        else:
            self._json(200, {})


def serve():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def run_kit(args, home, server):
    env = dict(os.environ)
    env.update({"HOME": home,
                "ROOM_SERVER": server,
                "TEAM_ROOM_TRUST_SERVER": "1",
                "TEAM_ROOM_TOKEN": "static-stub-token",
                "TEAM_ROOM_HEALTH_LOG": os.path.join(home, "health.jsonl")})
    env.pop("ROOM_JSON", None)
    env.pop("TEAM_ROOM_ORG_ID", None)
    return subprocess.run([sys.executable, KIT, *args], env=env,
                          capture_output=True, text=True, timeout=60)


def room_json(home):
    p = os.path.join(home, ".config", "team-room", "room.json")
    return json.load(open(p)) if os.path.exists(p) else None


def reset(teams=None):
    Stub.teams = list(teams or [])
    Stub.created, Stub.threads, Stub.schemas = [], [], []
    Stub.team_post_status = None
    Stub.schema_status = None
    CALLS.clear()


def main():
    httpd, server = serve()
    failures = []

    def check(label, cond, detail=""):
        if cond:
            print(f"  ok   {label}")
        else:
            print(f"  FAIL {label} {detail}")
            failures.append(label)

    try:
        # ── a company with no room: person one makes it ──────────────────
        print("person one creates the room")
        reset(teams=[])
        with tempfile.TemporaryDirectory() as home:
            r = run_kit(["create", "Northwind"], home, server)
            check("command succeeds", r.returncode == 0, r.stderr.strip())

            team = Stub.created[0] if Stub.created else {}
            grants = (team.get("acl") or {}).get("grants") or [{}]
            meta = team.get("metadata") or {}

            # The two facts everyone after person one depends on.
            check("opens the room to the company",
                  grants[0].get("principal_type") == "org"
                  and grants[0].get("principal") == MY_ORG
                  and "read" in (grants[0].get("actions") or []),
                  str(grants))
            check("labels it as this company's room",
                  meta.get("system_role") == ROOM_LABEL
                  and meta.get("room_org_id") == MY_ORG, str(meta))
            check("names it what was asked for", team.get("name") == "Northwind")

            # A room without its conversation is not a room.
            check("creates the room's conversation", len(Stub.threads) == 1)
            check("conversation is titled 'team room'",
                  (Stub.threads[0]["body"].get("thread") or {}).get("title")
                  == "team room")

            # Silent-later failures if these are missing.
            keys = sorted(s.get("lookup_key") for s in Stub.schemas)
            check("provisions records, pins and presence",
                  keys == ["room-pin", "team-presence", "team-record"], str(keys))
            check("schemas are scoped to the new team",
                  all(s.get("team") == "tem_new" for s in Stub.schemas))

            # And the person is left ready to post, not holding ids.
            cfg = room_json(home) or {}
            check("saves the room locally",
                  cfg.get("team_id") == "tem_new"
                  and cfg.get("thread_id") == "thr_new", str(cfg))
            check("tells them how teammates get in",
                  "room-post login" in r.stdout, r.stdout.strip())

        # ── the race: two colleagues run it at once ──────────────────────
        print("a company never ends up with two rooms")
        reset(teams=[{"id": "tem_real", "name": "Northwind", "org": MY_ORG,
                      "created_at": "2026-01-01T00:00:00Z",
                      "metadata": {"system_role": ROOM_LABEL,
                                   "room_org_id": MY_ORG},
                      "threads": [{"id": "thr_real", "title": "team room"}]}])
        with tempfile.TemporaryDirectory() as home:
            r = run_kit(["create", "Northwind"], home, server)
            check("succeeds without creating a second room",
                  r.returncode == 0 and not Stub.created,
                  f"created={Stub.created}")
            cfg = room_json(home) or {}
            check("adopts the room that already existed",
                  cfg.get("team_id") == "tem_real", str(cfg))

        # ── a lookup that FAILED is not a company without a room ─────────
        print("a broken lookup does not become a duplicate room")
        reset(teams=[])
        Stub.team_post_status = 500
        with tempfile.TemporaryDirectory() as home:
            r = run_kit(["create", "Northwind"], home, server)
            check("reports the failure instead of claiming success",
                  r.returncode != 0, r.stdout.strip())
            check("saves nothing when creation failed",
                  room_json(home) is None)

        # ── a schema that already exists is not an error ─────────────────
        print("re-running against existing schemas is fine")
        reset(teams=[])
        Stub.schema_status = 409
        with tempfile.TemporaryDirectory() as home:
            r = run_kit(["create", "Northwind"], home, server)
            check("treats 'already there' as done", r.returncode == 0,
                  r.stderr.strip())
            check("still saves the room", (room_json(home) or {}).get("team_id")
                  == "tem_new")
    finally:
        httpd.shutdown()

    print()
    if failures:
        print(f"FAILED: {len(failures)} — {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Signing in puts you in your company's room, without asking anyone.

    python3 tests/test_join_company_room.py

The wall this removes: a teammate installs the kit, signs in, is already in
the right company by email domain, and is told to go and ask a colleague to
add them. Every person after the first hit it, so a company quietly ended up
with a room per person, or with one person's room and everybody else outside.

Rooms carry a label in their team metadata saying they are a room and which
company owns them, so one query finds the right one whether or not the caller
is a member yet. Joining is a single call the kit makes on their behalf; the
person is never asked to do anything.

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

# The genuine room: older, and the platform records it as owned by my company.
REAL = {"id": "tem_real", "name": "Northwind", "org": MY_ORG,
        "created_at": "2026-01-01T00:00:00Z", "membership_status": None}

# A team someone else made, labelled with MY company's id and opened to it.
# Anyone can write metadata, so this arrives looking exactly like the real
# thing. Only `org`, which the platform sets from the creator, tells them
# apart. It is also NEWER, so a naive "most recent" pick would choose it.
FORGED = {"id": "tem_forged", "name": "Northwind", "org": "org_attacker",
          "created_at": "2026-07-01T00:00:00Z", "membership_status": None}


class Stub(http.server.BaseHTTPRequestHandler):
    joined = set()

    def log_message(self, *a):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        CALLS.append(("GET", self.path))
        if self.path.startswith("/api/v1/teams/tem_"):
            team_id = self.path.split("/api/v1/teams/")[1].split("?")[0]
            # Threads are only readable once you are a member, which is the
            # whole reason a label is needed to identify a room from outside.
            if team_id not in Stub.joined:
                self._json(403, {"error": "forbidden"})
                return
            self._json(200, {"id": team_id, "name": "Northwind",
                             "threads": [{"id": "thr_real", "title": "team room"}]})
        elif self.path.startswith("/api/v1/teams"):
            rows = [REAL, FORGED]
            if "membership=joined" in self.path:
                rows = [dict(r, membership_status="member")
                        for r in rows if r["id"] in Stub.joined]
            self._json(200, {"data": rows, "has_next": False})
        else:
            self._json(200, {"data": []})

    def do_POST(self):
        CALLS.append(("POST", self.path))
        if self.path.endswith("/join"):
            Stub.joined.add(self.path.split("/api/v1/teams/")[1].split("/join")[0])
            self._json(200, {"id": "tem_real"})
        else:
            self._json(200, {})


def run_kit(args, home, server, extra_env=None):
    env = dict(os.environ)
    env.update({"HOME": home,
                "ROOM_SERVER": server,
                "TEAM_ROOM_TRUST_SERVER": "1",
                "TEAM_ROOM_TOKEN": "static-stub-token",
                "TEAM_ROOM_ORG_ID": MY_ORG,
                "TEAM_ROOM_HEALTH_LOG": os.path.join(home, "health.jsonl")})
    env.pop("ROOM_JSON", None)
    with open(os.path.join(home, ".gitconfig"), "w") as f:
        f.write("[user]\n\temail = teammate@northwind.test\n\tname = Teammate\n")
    env.update(extra_env or {})
    return subprocess.run([sys.executable, KIT, *args], env=env,
                          capture_output=True, text=True, timeout=60)


def room_json(home):
    p = os.path.join(home, ".config", "team-room", "room.json")
    return json.load(open(p)) if os.path.exists(p) else None


def test_a_teammate_is_joined_to_the_room_their_company_already_has():
    Stub.joined.clear()
    CALLS.clear()
    home = tempfile.mkdtemp()

    r = run_kit(["discover"], home, SERVER)

    assert "ask" not in r.stdout.lower(), (
        "still telling the teammate to go and ask someone:\n" + r.stdout + r.stderr)
    assert ("POST", "/api/v1/teams/tem_real/join") in CALLS, (
        "never joined the room:\n" + "\n".join(map(str, CALLS)))
    cfg = room_json(home)
    assert cfg and cfg["team_id"] == "tem_real" and cfg["thread_id"] == "thr_real", cfg
    print("PASS  a teammate is joined to the room their company already has")


def test_a_forged_room_is_not_joined():
    Stub.joined.clear()
    CALLS.clear()
    home = tempfile.mkdtemp()

    run_kit(["discover"], home, SERVER)

    # The forged team is newer and carries the same label. Joining it would
    # put this company's work in a stranger's room.
    assert ("POST", "/api/v1/teams/tem_forged/join") not in CALLS, (
        "joined a team that only CLAIMS to belong to this company")
    print("PASS  a forged room is not joined")


def main():
    global SERVER
    with socketserver.TCPServer(("127.0.0.1", 0), Stub) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        SERVER = f"http://127.0.0.1:{srv.server_address[1]}"
        test_a_teammate_is_joined_to_the_room_their_company_already_has()
        test_a_forged_room_is_not_joined()
    print("\nall join tests passed")


if __name__ == "__main__":
    main()

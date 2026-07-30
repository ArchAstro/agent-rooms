#!/usr/bin/env python3
"""Signing in puts you in your company's room, without asking anyone.

    python3 tests/test_join_company_room.py

The wall this removes: a teammate installs the kit, signs in, is already in
the right company by email domain, and is told to go and ask a colleague to
add them. Every person after the first hit it, so a company quietly ended up
with a room per person, or with one person's room and everybody else outside.

Rooms carry a label in their team metadata saying they are a room and which
company owns them. Membership-scoped queries distinguish an existing room
from one the caller may join, while an unlabelled fallback preserves older
rooms. Joining is a single call the kit makes on their behalf; the person is
never asked to do anything.

Runs in-process against a stub of the API, no network.
"""
import http.server
import importlib.util
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "skills", "team-room", "room_post.py")

CALLS = []
MESSAGE_ATTEMPTS = []

MY_ORG = "org_mine"
ROOM_LABEL = "archastro_team_room"

# The genuine room: older, and the platform records it as owned by my company.
ROOM_METADATA = {"system_role": ROOM_LABEL, "room_org_id": MY_ORG}
REAL = {"id": "tem_real", "name": "Northwind", "org": MY_ORG,
        "created_at": "2026-01-01T00:00:00Z", "membership_status": None,
        "metadata": ROOM_METADATA}

# A team someone else made, labelled with MY company's id and opened to it.
# Anyone can write metadata, so this arrives looking exactly like the real
# thing. Only `org`, which the platform sets from the creator, tells them
# apart. It is also NEWER, so a naive "most recent" pick would choose it.
FORGED = {"id": "tem_forged", "name": "Northwind", "org": "org_attacker",
          "created_at": "2026-07-01T00:00:00Z", "membership_status": None,
          "metadata": ROOM_METADATA}

SAME_ORG_SECOND = {
    "id": "tem_second",
    "name": "Northwind Shadow",
    "org": MY_ORG,
    "created_at": "2025-01-01T00:00:00Z",
    "membership_status": None,
    "metadata": ROOM_METADATA,
}

LEGACY = {
    "id": "tem_legacy",
    "name": "Northwind Legacy",
    "org": MY_ORG,
    "created_at": "2024-01-01T00:00:00Z",
    "membership_status": None,
    "metadata": {},
}

FOREIGN_LEGACY = dict(
    LEGACY,
    id="tem_foreign_legacy",
    name="Foreign Legacy",
    org="org_attacker",
)


class Stub(http.server.BaseHTTPRequestHandler):
    joined = set()
    teams = [REAL, FORGED]
    paginate_joinable = False
    fail_me_status = None
    courier_message_status = 403
    human_message_status = None
    threads = {
        "tem_real": [{"id": "thr_real", "title": "team room"}],
        "tem_forged": [{"id": "thr_forged", "title": "team room"}],
        "tem_second": [{"id": "thr_second", "title": "team room"}],
        "tem_legacy": [{"id": "thr_legacy", "title": "team room"}],
        "tem_foreign_legacy": [{"id": "thr_foreign", "title": "team room"}],
    }

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
        token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        if self.path.startswith("/org/cli-auth"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            callback = query["redirect_uri"][-1]
            sep = "&" if "?" in callback else "?"
            target = callback + sep + urllib.parse.urlencode({
                "access_token": "human-token",
                "refresh_token": "refresh",
                "app": "app",
                "org": MY_ORG,
                "user": "usr_teammate",
                "email": "teammate@northwind.test",
                "expires_in": "900",
            })
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        if self.path.startswith("/api/v1/users/me"):
            if Stub.fail_me_status:
                self._json(Stub.fail_me_status, {"error": "identity unavailable"})
                return
            org = "org_attacker" if token == "courier-token" else MY_ORG
            self._json(200, {"id": "usr_teammate", "org": org, "app_id": "app"})
            return
        if self.path.startswith("/api/v1/teams/tem_"):
            team_id = self.path.split("/api/v1/teams/")[1].split("?")[0]
            # Threads are only readable once you are a member, which is the
            # whole reason a label is needed to identify a room from outside.
            if team_id not in Stub.joined:
                self._json(403, {"error": "forbidden"})
                return
            self._json(200, {"id": team_id, "name": "Northwind",
                             "threads": Stub.threads.get(team_id, [])})
        elif self.path.startswith("/api/v1/teams"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            rows = list(Stub.teams)
            if "metadata" in query:
                expected_org = "org_attacker" if token == "courier-token" else MY_ORG
                metadata_filter = json.loads(query["metadata"][0])
                assert metadata_filter == {
                    "operator": "and",
                    "clauses": [
                        {
                            "operator": "eq",
                            "path": ["system_role"],
                            "value": ROOM_LABEL,
                        },
                        {
                            "operator": "eq",
                            "path": ["room_org_id"],
                            "value": expected_org,
                        },
                    ],
                }, metadata_filter
                rows = [
                    r for r in rows
                    if (r.get("metadata") or {}).get("system_role") == ROOM_LABEL
                    and (r.get("metadata") or {}).get("room_org_id") == expected_org
                ]
            if query.get("membership") == ["joined"]:
                rows = [dict(r, membership_status="member")
                        for r in rows if r["id"] in Stub.joined]
            elif query.get("membership") == ["joinable"]:
                rows = [r for r in rows if r["id"] not in Stub.joined]
                if Stub.paginate_joinable:
                    page = int(query.get("page", ["1"])[0])
                    rows = [FORGED] if page == 1 else [REAL]
                    self._json(200, {"data": rows, "has_next": page == 1})
                    return
            self._json(200, {"data": rows, "has_next": False})
        else:
            self._json(200, {"data": []})

    def do_POST(self):
        CALLS.append(("POST", self.path))
        token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        if self.path.endswith("/join"):
            Stub.joined.add(self.path.split("/api/v1/teams/")[1].split("/join")[0])
            # The real self-join endpoint succeeds with no response body.
            self.send_response(204)
            self.end_headers()
        elif "/messages" in self.path:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            MESSAGE_ATTEMPTS.append({
                "token": token,
                "path": self.path,
                "body": body,
            })
            status = (
                Stub.courier_message_status
                if token == "courier-token"
                else Stub.human_message_status
            )
            if status:
                self._json(status, {"error": "message rejected"})
            else:
                self._json(200, {})
        else:
            self._json(200, {})


def run_kit(args, home, server, extra_env=None):
    env = dict(os.environ)
    env.update({"HOME": home,
                "ROOM_SERVER": server,
                "TEAM_ROOM_TRUST_SERVER": "1",
                "TEAM_ROOM_TOKEN": "static-stub-token",
                "TEAM_ROOM_HEALTH_LOG": os.path.join(home, "health.jsonl")})
    env.pop("ROOM_JSON", None)
    env.pop("TEAM_ROOM_ORG_ID", None)
    with open(os.path.join(home, ".gitconfig"), "w") as f:
        f.write("[user]\n\temail = teammate@northwind.test\n\tname = Teammate\n")
    for key, value in (extra_env or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run([sys.executable, KIT, *args], env=env,
                          capture_output=True, text=True, timeout=60)


def room_json(home):
    p = os.path.join(home, ".config", "team-room", "room.json")
    return json.load(open(p)) if os.path.exists(p) else None


def reset(teams=None, joined=None, threads=None):
    Stub.teams = list([REAL, FORGED] if teams is None else teams)
    Stub.joined = set([] if joined is None else joined)
    Stub.paginate_joinable = False
    Stub.fail_me_status = None
    Stub.courier_message_status = 403
    Stub.human_message_status = None
    Stub.threads = dict({
        "tem_real": [{"id": "thr_real", "title": "team room"}],
        "tem_forged": [{"id": "thr_forged", "title": "team room"}],
        "tem_second": [{"id": "thr_second", "title": "team room"}],
        "tem_legacy": [{"id": "thr_legacy", "title": "team room"}],
        "tem_foreign_legacy": [{"id": "thr_foreign", "title": "team room"}],
    } if threads is None else threads)
    CALLS.clear()
    MESSAGE_ATTEMPTS.clear()


def test_a_teammate_is_joined_to_the_room_their_company_already_has():
    reset()
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
    reset()
    home = tempfile.mkdtemp()

    run_kit(["discover"], home, SERVER)

    # The forged team is newer and carries the same label. Joining it would
    # put this company's work in a stranger's room.
    assert ("POST", "/api/v1/teams/tem_forged/join") not in CALLS, (
        "joined a team that only CLAIMS to belong to this company")
    print("PASS  a forged room is not joined")


def test_environment_cannot_choose_the_company_to_join():
    reset()
    home = tempfile.mkdtemp()

    run_kit(
        ["discover"],
        home,
        SERVER,
        {"TEAM_ROOM_ORG_ID": "org_attacker"},
    )

    assert ("POST", "/api/v1/teams/tem_real/join") in CALLS, CALLS
    assert ("POST", "/api/v1/teams/tem_forged/join") not in CALLS, CALLS
    assert room_json(home)["team_id"] == "tem_real"
    print("PASS  an environment variable cannot choose another company")


def test_two_company_rooms_are_ambiguous_and_join_neither():
    reset([REAL, SAME_ORG_SECOND])
    home = tempfile.mkdtemp()

    r = run_kit(["discover"], home, SERVER)

    assert not [c for c in CALLS if c[0] == "POST"], CALLS
    assert room_json(home) is None
    assert "more than one" in (r.stdout + r.stderr).lower(), r.stdout + r.stderr
    print("PASS  two company rooms fail safely instead of guessing")


def test_a_joined_unlabelled_legacy_room_is_still_discovered():
    reset([LEGACY], joined={"tem_legacy"})
    home = tempfile.mkdtemp()

    run_kit(["discover"], home, SERVER)

    cfg = room_json(home)
    assert cfg and cfg["team_id"] == "tem_legacy", cfg
    assert not [c for c in CALLS if c[0] == "POST"], CALLS
    print("PASS  an existing unlabelled room survives fresh-machine discovery")


def write_login(home, token="human-token"):
    path = os.path.join(home, ".config", "team-room", "credentials.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({
            "server": SERVER,
            "orgSessions": {
                "app": {
                    "accessToken": token,
                    "refreshToken": "refresh",
                    "appId": "app",
                    "orgId": MY_ORG,
                    "userId": "usr_teammate",
                    "expiresAt": 4_102_444_800_000,
                }
            },
        }, f)


def test_browser_login_beats_a_courier_token_for_discovery():
    reset()
    home = tempfile.mkdtemp()
    write_login(home)

    run_kit(
        ["discover"],
        home,
        SERVER,
        {"TEAM_ROOM_TOKEN": "courier-token"},
    )

    cfg = room_json(home)
    assert cfg and cfg["team_id"] == "tem_real", (cfg, CALLS)
    assert ("POST", "/api/v1/teams/tem_forged/join") not in CALLS, CALLS
    print("PASS  browser identity wins over a courier token")


def test_a_malformed_room_is_an_error_not_no_room():
    reset(
        [REAL],
        threads={"tem_real": [{"id": "thr_other", "title": "general"}]},
    )
    home = tempfile.mkdtemp()

    r = run_kit(["discover"], home, SERVER)

    assert room_json(home) is None
    output = (r.stdout + r.stderr).lower()
    assert "joined" in output and "nothing was changed" not in output, output
    print("PASS  a malformed room is reported as a failed check")


def test_company_room_discovery_reads_every_joinable_page():
    reset()
    Stub.paginate_joinable = True
    home = tempfile.mkdtemp()

    run_kit(["discover"], home, SERVER)

    cfg = room_json(home)
    assert cfg and cfg["team_id"] == "tem_real", (cfg, CALLS)
    assert any("membership=joinable" in path and "page=2" in path
               for method, path in CALLS if method == "GET"), CALLS
    print("PASS  room discovery drains joinable pagination")


def test_a_joined_foreign_labelled_room_cannot_win_discovery():
    reset([REAL, FORGED], joined={"tem_forged"})
    home = tempfile.mkdtemp()

    run_kit(["discover"], home, SERVER)

    cfg = room_json(home)
    assert cfg and cfg["team_id"] == "tem_real", (cfg, CALLS)
    print("PASS  an old foreign labelled membership is ignored")


def test_a_joined_foreign_legacy_room_cannot_win_discovery():
    reset([REAL, FOREIGN_LEGACY], joined={"tem_foreign_legacy"})
    home = tempfile.mkdtemp()

    run_kit(["discover"], home, SERVER)

    cfg = room_json(home)
    assert cfg and cfg["team_id"] == "tem_real", (cfg, CALLS)
    print("PASS  an old foreign legacy membership is ignored")


def test_identity_outage_is_not_reported_as_no_company_room():
    reset()
    Stub.fail_me_status = 500
    home = tempfile.mkdtemp()

    r = run_kit(["discover"], home, SERVER)

    assert room_json(home) is None
    output = (r.stdout + r.stderr).lower()
    assert "couldn't check" in output and "doesn't have" not in output, output
    assert not [c for c in CALLS if c[0] == "POST"], CALLS
    print("PASS  an identity outage fails closed")


def test_corrupt_human_credentials_do_not_fall_back_to_a_courier():
    reset()
    home = tempfile.mkdtemp()
    path = os.path.join(home, ".config", "team-room", "credentials.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{broken")

    run_kit(
        ["discover"],
        home,
        SERVER,
        {"TEAM_ROOM_TOKEN": "courier-token"},
    )

    assert room_json(home) is None
    assert CALLS == [], CALLS
    print("PASS  corrupt human credentials never switch to a courier")


def test_untrusted_discovery_server_never_receives_the_token():
    reset()
    home = tempfile.mkdtemp()

    r = run_kit(
        ["discover"],
        home,
        SERVER,
        {"TEAM_ROOM_TRUST_SERVER": None},
    )

    assert CALLS == [], CALLS
    assert "refus" in (r.stdout + r.stderr).lower(), r.stdout + r.stderr
    print("PASS  an untrusted discovery server receives no bearer token")


def write_room_config(path, team_id, thread_id, app_slug="agentnetwork"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({
            "thread_id": thread_id,
            "team_id": team_id,
            "server": SERVER,
            "portal": SERVER,
            "app_slug": app_slug,
            "publishable_key": "stub-publishable-key",
        }, f)


def load_kit_module(home, room_json_path=None):
    old_home = os.environ.get("HOME")
    old_room_json = os.environ.get("ROOM_JSON")
    old_trust = os.environ.get("TEAM_ROOM_TRUST_SERVER")
    old_argv = list(sys.argv)
    os.environ["HOME"] = home
    os.environ["TEAM_ROOM_TRUST_SERVER"] = "1"
    if room_json_path:
        os.environ["ROOM_JSON"] = room_json_path
    else:
        os.environ.pop("ROOM_JSON", None)
    sys.argv = [KIT, "help"]
    try:
        spec = importlib.util.spec_from_file_location(
            "room_post_login_test_" + uuid.uuid4().hex,
            KIT,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.DEFAULT_PORTAL = SERVER
        module.DEFAULT_SERVER = SERVER
        return module
    finally:
        sys.argv = old_argv
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home
        if old_room_json is None:
            os.environ.pop("ROOM_JSON", None)
        else:
            os.environ["ROOM_JSON"] = old_room_json
        if old_trust is None:
            os.environ.pop("TEAM_ROOM_TRUST_SERVER", None)
        else:
            os.environ["TEAM_ROOM_TRUST_SERVER"] = old_trust


def run_browser_login(module):
    import webbrowser

    old_open = webbrowser.open
    opened = []

    def open_callback(url):
        opened.append(url)
        def visit():
            with urllib.request.urlopen(url, timeout=5) as response:
                response.read()
        threading.Thread(target=visit, daemon=True).start()
        return True

    webbrowser.open = open_callback
    try:
        module.login(timeout=5)
    finally:
        webbrowser.open = old_open
    assert len(opened) == 1, opened
    return opened[0]


def test_browser_login_ends_with_a_usable_company_room():
    reset()
    home = tempfile.mkdtemp()
    module = load_kit_module(home)

    run_browser_login(module)

    cfg = room_json(home)
    assert cfg and cfg["team_id"] == "tem_real", (cfg, CALLS)
    creds = os.path.join(home, ".config", "team-room", "credentials.json")
    assert os.path.exists(creds)
    assert ("POST", "/api/v1/teams/tem_real/join") in CALLS, CALLS

    posted = run_kit(
        ["done", "first Stripe pilot post"],
        home,
        SERVER,
        {"TEAM_ROOM_TOKEN": None},
    )
    assert posted.returncode == 0, posted.stdout + posted.stderr
    assert any(
        method == "POST"
        and "/threads/thr_real/messages" in path
        for method, path in CALLS
    ), CALLS
    print("PASS  browser login ends with a usable room and first post")


def test_first_post_falls_back_to_the_human_login_when_a_courier_is_for_another_room():
    reset()
    home = tempfile.mkdtemp()
    module = load_kit_module(home)

    run_browser_login(module)

    posted = run_kit(
        ["done", "first Stripe pilot post"],
        home,
        SERVER,
        {"TEAM_ROOM_TOKEN": "courier-token"},
    )

    assert posted.returncode == 0, posted.stdout + posted.stderr
    assert [attempt["token"] for attempt in MESSAGE_ATTEMPTS] == [
        "courier-token",
        "human-token",
    ], MESSAGE_ATTEMPTS
    assert all(
        "/apps/app/threads/thr_real/messages" in attempt["path"]
        for attempt in MESSAGE_ATTEMPTS
    ), MESSAGE_ATTEMPTS
    assert all(
        attempt["body"]["user"] == "usr_teammate"
        and attempt["body"]["content"].endswith(": first Stripe pilot post")
        for attempt in MESSAGE_ATTEMPTS
    ), MESSAGE_ATTEMPTS
    print("PASS  a foreign courier cannot make the human's first post fail")


def test_first_post_ignores_a_stale_courier_token_file_after_human_login():
    reset()
    home = tempfile.mkdtemp()
    token_path = os.path.join(home, ".config", "team-room", "token")
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w") as f:
        f.write("courier-token")
    module = load_kit_module(home)

    run_browser_login(module)

    posted = run_kit(
        ["done", "first Stripe pilot post"],
        home,
        SERVER,
        {"TEAM_ROOM_TOKEN": None},
    )

    assert posted.returncode == 0, posted.stdout + posted.stderr
    assert [attempt["token"] for attempt in MESSAGE_ATTEMPTS] == [
        "courier-token",
        "human-token",
    ], MESSAGE_ATTEMPTS
    assert all(
        "/apps/app/threads/thr_real/messages" in attempt["path"]
        and attempt["body"]["user"] == "usr_teammate"
        for attempt in MESSAGE_ATTEMPTS
    ), MESSAGE_ATTEMPTS
    print("PASS  a stale courier token file cannot break the human's first post")


def test_an_authorized_courier_posts_once_without_using_the_human_login():
    reset()
    Stub.courier_message_status = None
    home = tempfile.mkdtemp()
    module = load_kit_module(home)
    run_browser_login(module)

    posted = run_kit(
        ["done", "courier post"],
        home,
        SERVER,
        {"TEAM_ROOM_TOKEN": "courier-token"},
    )

    assert posted.returncode == 0, posted.stdout + posted.stderr
    assert [attempt["token"] for attempt in MESSAGE_ATTEMPTS] == [
        "courier-token",
    ], MESSAGE_ATTEMPTS
    assert MESSAGE_ATTEMPTS[0]["body"]["user"] == "usr_teammate"
    print("PASS  an authorized courier remains the single posting principal")


def test_courier_fallback_is_narrow_and_bounded():
    for status, expected_tokens in (
        (401, ["courier-token", "human-token"]),
        (404, ["courier-token", "human-token"]),
        (500, ["courier-token"]),
    ):
        reset()
        Stub.courier_message_status = status
        home = tempfile.mkdtemp()
        module = load_kit_module(home)
        run_browser_login(module)

        run_kit(
            ["done", f"courier status {status}"],
            home,
            SERVER,
            {"TEAM_ROOM_TOKEN": "courier-token"},
        )

        assert [attempt["token"] for attempt in MESSAGE_ATTEMPTS] == expected_tokens, (
            status,
            MESSAGE_ATTEMPTS,
        )

    reset()
    Stub.courier_message_status = 403
    Stub.human_message_status = 403
    home = tempfile.mkdtemp()
    module = load_kit_module(home)
    run_browser_login(module)

    run_kit(
        ["done", "both principals rejected"],
        home,
        SERVER,
        {"TEAM_ROOM_TOKEN": "courier-token"},
    )

    assert [attempt["token"] for attempt in MESSAGE_ATTEMPTS] == [
        "courier-token",
        "human-token",
    ], MESSAGE_ATTEMPTS
    print("PASS  courier fallback covers auth mismatch without retry loops")


def test_repo_controlled_app_slug_cannot_inject_a_second_callback():
    reset()
    home = tempfile.mkdtemp()
    pinned = os.path.join(tempfile.mkdtemp(), "room.json")
    malicious_slug = "agentnetwork&redirect_uri=https://evil.example/callback"
    write_room_config(
        pinned,
        "tem_real",
        "thr_real",
        app_slug=malicious_slug,
    )
    module = load_kit_module(home, room_json_path=pinned)

    os.environ["ROOM_JSON"] = pinned
    try:
        opened_url = run_browser_login(module)
    finally:
        os.environ.pop("ROOM_JSON", None)

    query = urllib.parse.parse_qs(urllib.parse.urlparse(opened_url).query)
    assert query["slug"] == [malicious_slug], query
    assert len(query["redirect_uri"]) == 1, query
    assert query["redirect_uri"][0].startswith("http://127.0.0.1:"), query
    print("PASS  a repo-controlled app slug cannot replace the login callback")


def test_browser_login_fails_when_room_connection_is_incomplete():
    reset()
    Stub.fail_me_status = 500
    home = tempfile.mkdtemp()
    module = load_kit_module(home)

    try:
        run_browser_login(module)
    except SystemExit as exc:
        assert exc.code not in (0, None), exc.code
    else:
        raise AssertionError("login reported success without a room")

    assert room_json(home) is None
    print("PASS  browser login cannot report success without a room")


def test_browser_login_replaces_a_stale_foreign_machine_room():
    reset([REAL, FOREIGN_LEGACY], joined={"tem_foreign_legacy"})
    home = tempfile.mkdtemp()
    machine_room = os.path.join(home, ".config", "team-room", "room.json")
    write_room_config(machine_room, "tem_foreign_legacy", "thr_foreign")
    module = load_kit_module(home)

    run_browser_login(module)

    cfg = room_json(home)
    assert cfg and cfg["team_id"] == "tem_real", (cfg, CALLS)
    assert ("POST", "/api/v1/teams/tem_real/join") in CALLS, CALLS
    print("PASS  login replaces a stale room from a previous company")


def test_browser_login_joins_an_org_valid_pinned_room():
    reset([REAL])
    home = tempfile.mkdtemp()
    pinned = os.path.join(tempfile.mkdtemp(), "room.json")
    write_room_config(pinned, "tem_real", "thr_real")
    module = load_kit_module(home, room_json_path=pinned)

    os.environ["ROOM_JSON"] = pinned
    try:
        run_browser_login(module)
    finally:
        os.environ.pop("ROOM_JSON", None)

    assert ("POST", "/api/v1/teams/tem_real/join") in CALLS, CALLS
    assert json.load(open(pinned))["team_id"] == "tem_real"
    assert room_json(home) is None
    print("PASS  login self-joins a valid explicitly pinned room")


def main():
    global SERVER
    with socketserver.TCPServer(("127.0.0.1", 0), Stub) as srv:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        SERVER = f"http://127.0.0.1:{srv.server_address[1]}"
        test_a_teammate_is_joined_to_the_room_their_company_already_has()
        test_a_forged_room_is_not_joined()
        test_environment_cannot_choose_the_company_to_join()
        test_two_company_rooms_are_ambiguous_and_join_neither()
        test_a_joined_unlabelled_legacy_room_is_still_discovered()
        test_browser_login_beats_a_courier_token_for_discovery()
        test_a_malformed_room_is_an_error_not_no_room()
        test_company_room_discovery_reads_every_joinable_page()
        test_a_joined_foreign_labelled_room_cannot_win_discovery()
        test_a_joined_foreign_legacy_room_cannot_win_discovery()
        test_identity_outage_is_not_reported_as_no_company_room()
        test_corrupt_human_credentials_do_not_fall_back_to_a_courier()
        test_untrusted_discovery_server_never_receives_the_token()
        test_browser_login_ends_with_a_usable_company_room()
        test_first_post_falls_back_to_the_human_login_when_a_courier_is_for_another_room()
        test_first_post_ignores_a_stale_courier_token_file_after_human_login()
        test_an_authorized_courier_posts_once_without_using_the_human_login()
        test_courier_fallback_is_narrow_and_bounded()
        test_repo_controlled_app_slug_cannot_inject_a_second_callback()
        test_browser_login_fails_when_room_connection_is_incomplete()
        test_browser_login_replaces_a_stale_foreign_machine_room()
        test_browser_login_joins_an_org_valid_pinned_room()
    print("\nall join tests passed")


if __name__ == "__main__":
    main()

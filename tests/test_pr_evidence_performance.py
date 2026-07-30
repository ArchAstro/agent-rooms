#!/usr/bin/env python3
"""Measured publisher limits: bounded encoding and unchanged no-write path."""
import base64
import http.server
import os
import resource
import subprocess
import threading
import time
from pathlib import Path
import sys
import tempfile
import statistics

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "team-room"))
from evidence.artifacts import encode_artifact
from evidence.bundle import rebuild_payload
from evidence.publisher import Publisher
from evidence.policy import Policy
from evidence.publisher import PublishRequest
from test_pr_evidence_publish import ContractServer, commit, producer, run_publish

SHA = "a" * 40

class LocalClient:
    def __init__(self): self.artifact = None; self.writes = 0
    def list_artifacts(self): return [] if self.artifact is None else [self.artifact]
    def show_artifact(self, _): return self.artifact
    def create_artifact(self, name, content):
        self.writes += 1; self.artifact = {"id":"a", "name":name,"version":1,"file_name":"pr-evidence.json","content_type":"application/json","content":content}; return self.artifact
    def update_artifact(self, _, content, version):
        self.writes += 1; self.artifact={**self.artifact,"version":version+1,"content":content}; return self.artifact
    def list_messages(self): return [{"content":"pr-evidence:initial:subject"}]
    def create_message(self, *_): self.writes += 1; return {"id":"m"}

def request(session):
    content = {"schema":"agent-room-pr-evidence/v1","subject":{"key":"subject","repository":"github.com/owner/repository","pr_number":7,"pr_url":None,"base_ref":"main","base_sha":SHA,"merge_base_sha":SHA,"head_sha":SHA},"current":{"complete":False,"capture_mode":"review_capsule","capture_fidelity":"exact","generated_at":"2026-01-01T00:00:00Z"},"chapters":[{"session_id":session,"capture_fidelity":"exact","prompts":["p"],"events":[{"event_id":session+":1","sequence":1,"type":"test","summary":"pytest","data":{"command":"pytest","outcome":"passed"}}],"execution_spans":[]}],"patch":{"text":"x","stats":{"files":1,"added":1,"deleted":0}},"tests":[{"command":"pytest","outcome":"passed"}],"provenance":{},"redactions":[],"omissions":[],"rendered_markdown":""}
    content = rebuild_payload(content, content["chapters"])
    return PublishRequest(
        "subject", "pr-evidence--owner-repository--7--x",
        SHA, SHA, session, content,
    )


def test_artifact_base64_and_warm_unchanged_path_stay_bounded():
    raw = (b'{"schema":"agent-room-pr-evidence/v1","x":"' + b"x" * (3 * 1024 * 1024 - 100) + b'"}')
    started = time.monotonic(); encoded, stats = encode_artifact(raw); elapsed = time.monotonic() - started
    assert len(raw) <= 3 * 1024 * 1024 and len(encoded) <= 4 * 1024 * 1024
    assert stats.raw_bytes == len(raw) and stats.base64_bytes == len(encoded)
    assert elapsed < 5
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = rss if sys.platform == "darwin" else rss * 1024
    assert rss_bytes < 128 * 1024 * 1024
    print(f"PASS  bounded encode raw={len(raw)} base64={len(encoded)} seconds={elapsed:.3f} maxrss={rss_bytes}")


def test_real_publisher_cold_append_and_unchanged_benchmark_has_samples_and_rss_budget():
    def run(kind):
        values=[]
        for n in range(35):
            with tempfile.TemporaryDirectory() as td:
                client=LocalClient(); publisher=Publisher(client, Path(td)/"state.json", Policy())
                if kind == "cold": action=lambda: publisher.publish(request("session-a"))
                elif kind == "append":
                    publisher.publish(request("session-a")); action=lambda: publisher.publish(request("session-b"))
                else:
                    publisher.publish(request("session-a")); action=lambda: publisher.publish(request("session-a"))
                start=time.monotonic(); result=action(); values.append(time.monotonic()-start)
                expected = "unchanged" if kind == "unchanged" else ("published" if kind == "cold" else "updated")
                assert result.status == expected, (kind, result)
        return values[5:]
    metrics={kind: run(kind) for kind in ("cold","append","unchanged")}
    for kind, samples in metrics.items():
        assert len(samples)==30
        p50=statistics.median(samples); p95=sorted(samples)[int(.95*len(samples))]
        budget = {"cold": 5.0, "append": 1.0, "unchanged": 0.25}[kind]
        assert p95 <= budget, (kind, p95, budget)
        print(f"PASS  {kind} samples=30 p50={p50:.4f}s p95={p95:.4f}s")
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS returns bytes; Linux returns KiB.
    rss_bytes=rss if sys.platform == "darwin" else rss*1024
    assert rss_bytes < 128*1024*1024
    print(f"PASS  publisher benchmark max_rss_bytes={rss_bytes}")


def test_real_cli_git_and_tcp_unchanged_path_has_a_measured_p95_budget():
    ContractServer.artifacts = {}; ContractServer.messages = []; ContractServer.writes = []; ContractServer.reads = []
    with tempfile.TemporaryDirectory() as td, http.server.ThreadingHTTPServer(("127.0.0.1", 0), ContractServer) as srv:
        root = Path(td); repo = root / "repo"; repo.mkdir(); home = root / "home"; home.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "remote", "add", "origin", "git@github.com:owner/repository.git"], cwd=repo, check=True)
        base = commit(repo, "base"); head = commit(repo, "head"); producer(home / "producer.py")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        endpoint = f"http://127.0.0.1:{srv.server_address[1]}"
        assert "published" in run_publish(repo, home, endpoint, base, head, "session-cli").stdout
        samples = []
        for _ in range(35):
            started = time.monotonic()
            result = run_publish(repo, home, endpoint, base, head, "session-cli")
            samples.append(time.monotonic() - started)
            assert result.returncode == 0 and "unchanged" in result.stdout
        measured = samples[5:]
        p95 = sorted(measured)[int(.95 * len(measured))]
        assert p95 < 2.0, p95
        assert len(ContractServer.artifacts) == 1 and ContractServer.artifacts["artifact-1"]["version"] == 1
        print(f"PASS  CLI Git TCP unchanged samples=30 p95={p95:.4f}s")


if __name__ == "__main__":
    test_artifact_base64_and_warm_unchanged_path_stay_bounded()
    test_real_publisher_cold_append_and_unchanged_benchmark_has_samples_and_rss_budget()
    test_real_cli_git_and_tcp_unchanged_path_has_a_measured_p95_budget()

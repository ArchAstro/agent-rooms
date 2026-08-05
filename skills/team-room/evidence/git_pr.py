"""Local-only PR identity and commit binding; this module never calls GitHub."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any


PR_URL = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/pull/(\d+)$")
SHA = re.compile(r"^[0-9a-f]{40,64}$")
AUTOMATIC_ENVELOPE_HEADER_MAX_BYTES = 16 * 1024
ASTRODEV_SESSION_HEAD_BYTES = 256 * 1024
ASTRODEV_SESSION_TAIL_BYTES = 256 * 1024


def no_lazy_fetch_env() -> dict[str, str]:
    return {**os.environ, "GIT_NO_LAZY_FETCH": "1"}


def parse_pr(value: str, repository: str) -> tuple[int, str]:
    found = PR_URL.fullmatch(value)
    if found:
        repo = f"github.com/{found.group(1).lower()}/{found.group(2).lower()}"
        if repo != repository:
            raise ValueError("PR URL repository does not match local origin")
        return int(found.group(3)), value
    if value.isdigit() and int(value) > 0:
        return int(value), f"https://{repository}/pull/{int(value)}"
    raise ValueError("PR must be a GitHub pull URL or a positive number")


def repository_identity(cwd: Path) -> str:
    remote = subprocess.check_output(
        ["git", "remote", "get-url", "origin"],
        cwd=cwd,
        env=no_lazy_fetch_env(),
        text=True,
        timeout=5,
    ).strip()
    remote = remote.removesuffix(".git").replace("git@github.com:", "github.com/").replace("https://", "")
    remote = re.sub(r"^ssh://git@github\.com[:/]", "github.com/", remote, flags=re.I)
    if not re.fullmatch(r"github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", remote):
        raise ValueError("local origin must identify an explicit github.com owner/repository")
    return remote.lower()


def _commit(cwd: Path, value: str) -> str:
    if not SHA.fullmatch(value):
        raise ValueError("base and head must be full lowercase local commit SHAs")
    actual = subprocess.check_output(
        ["git", "rev-parse", "--verify", value + "^{commit}"],
        cwd=cwd,
        env=no_lazy_fetch_env(),
        text=True,
        timeout=5,
    ).strip()
    if actual != value:
        raise ValueError("declared local commit SHA is not exact")
    return actual


def local_commits(cwd: Path, base_sha: str, head_sha: str) -> tuple[str, str, str]:
    base, head = _commit(cwd, base_sha), _commit(cwd, head_sha)
    merge = subprocess.check_output(
        ["git", "merge-base", base, head],
        cwd=cwd,
        env=no_lazy_fetch_env(),
        text=True,
        timeout=5,
    ).strip()
    return base, head, merge


def is_ancestor(cwd: Path, old: str, new: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", old, new],
        cwd=cwd,
        env=no_lazy_fetch_env(),
        timeout=5,
    ).returncode == 0


def handoff(path: str) -> dict[str, Any]:
    candidate = Path(path)
    before = candidate.lstat()
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > 16_384:
        raise ValueError("PR evidence handoff must have mode 0600")
    with candidate.open("rb") as handle:
        data = json.loads(handle.read(16_385).decode("utf-8"))
        after = os.fstat(handle.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("PR evidence handoff changed while read")
    allowed = {
        "pr",
        "pr_url",
        "base_ref",
        "base_sha",
        "head_sha",
        "session_id",
        "harness",
        "agent_type",
        "model",
        "capture_path",
    }
    if not isinstance(data, dict):
        raise ValueError("PR evidence handoff fields are invalid")
    # Tolerant reader on keys: an extra key a harness invented (a real 2026-08
    # failure sent pr_number) must not silently kill the whole publish — only
    # the allowed keys are ever consumed, so unknown ones are dropped. Values
    # of consumed keys stay strict.
    data = {key: value for key, value in data.items() if key in allowed}
    if any(not isinstance(value, str) or len(value) > 512 for value in data.values()):
        raise ValueError("PR evidence handoff fields are invalid")
    current = candidate.lstat()
    if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
        raise ValueError("PR evidence handoff changed before consumption")
    candidate.unlink()
    return data


def consume_private_file(path: str, maximum_bytes: int = 16 * 1024 * 1024) -> bytes:
    candidate = Path(path)
    before = candidate.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_size > maximum_bytes
    ):
        raise ValueError("PR evidence capture must be an owned mode-0600 regular file")
    with candidate.open("rb") as handle:
        data = handle.read(maximum_bytes + 1)
        after = os.fstat(handle.fileno())
    if len(data) > maximum_bytes:
        raise ValueError("PR evidence capture exceeds its byte limit")
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ValueError("PR evidence capture changed while read")
    current = candidate.lstat()
    if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
        raise ValueError("PR evidence capture changed before consumption")
    candidate.unlink()
    return data


def _complete_json_lines(value: bytes, discard_leading_partial: bool) -> list[dict]:
    if discard_leading_partial:
        newline = value.find(b"\n")
        value = b"" if newline < 0 else value[newline + 1 :]
    if value and not value.endswith(b"\n"):
        newline = value.rfind(b"\n")
        value = b"" if newline < 0 else value[: newline + 1]
    records = []
    for line in value.splitlines():
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _pread_exact(descriptor: int, length: int, offset: int) -> bytes:
    chunks = []
    remaining = length
    position = offset
    while remaining:
        chunk = os.pread(descriptor, remaining, position)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
        position += len(chunk)
    return b"".join(chunks)


def bounded_astrodev_session(
    path: str, session_id: str, declared_cwd: str, process_cwd: Path
) -> bytes:
    candidate = Path(path)
    before = candidate.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_uid != os.getuid()
    ):
        raise ValueError("AstroDev session must be an owned regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(candidate, flags)
    try:
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("AstroDev session changed before open")
        head_length = min(opened.st_size, ASTRODEV_SESSION_HEAD_BYTES)
        tail_start = max(
            head_length, opened.st_size - ASTRODEV_SESSION_TAIL_BYTES
        )
        head = _pread_exact(descriptor, head_length, 0)
        tail = _pread_exact(
            descriptor, opened.st_size - tail_start, tail_start
        )
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ValueError("AstroDev session changed while read")
    head_records = _complete_json_lines(head, False)
    discard_tail_prefix = tail_start > 0 and not (
        tail_start == head_length and head.endswith(b"\n")
    )
    tail_records = _complete_json_lines(tail, discard_tail_prefix)
    session = next(
        (record for record in head_records if record.get("type") == "session"),
        None,
    )
    if (
        not isinstance(session, dict)
        or session.get("id") != session_id
        or session.get("cwd") != declared_cwd
        or os.path.realpath(declared_cwd) != os.path.realpath(process_cwd)
    ):
        raise ValueError("AstroDev session identity or cwd does not match envelope")
    if not any(
        record.get("type") == "message"
        and isinstance(record.get("message"), dict)
        and record["message"].get("role") == "user"
        for record in head_records
    ):
        raise ValueError("AstroDev bounded capture could not preserve first prompt")
    records = list(head_records)
    head_complete_end = (
        len(head) if head.endswith(b"\n") else max(0, head.rfind(b"\n") + 1)
    )
    tail_leading_skip = 0
    if discard_tail_prefix and tail:
        newline = tail.find(b"\n")
        tail_leading_skip = len(tail) if newline < 0 else newline + 1
    omitted_bytes = max(
        0, tail_start + tail_leading_skip - head_complete_end
    )
    if omitted_bytes:
        records.append(
            {
                "type": "capture_omission",
                "omitted_bytes": omitted_bytes,
                "reason": "middle trajectory omitted from bounded AstroDev capture",
            }
        )
    records.extend(tail_records)
    return b"".join(
        json.dumps(record, separators=(",", ":")).encode("utf-8") + b"\n"
        for record in records
    )


def automatic_envelope(stream, process_cwd: Path) -> tuple[dict[str, Any], bytes]:
    prefix = stream.read(4)
    if len(prefix) != 4:
        raise ValueError("automatic PR evidence envelope is incomplete")
    header_length = int.from_bytes(prefix, "big")
    if not 0 < header_length <= AUTOMATIC_ENVELOPE_HEADER_MAX_BYTES:
        raise ValueError("automatic PR evidence envelope header exceeds byte cap")
    chunks = []
    remaining = header_length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise ValueError("automatic PR evidence envelope is incomplete")
        chunks.append(chunk)
        remaining -= len(chunk)
    if stream.read(1):
        raise ValueError("automatic PR evidence envelope has trailing bytes")
    try:
        supplied = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("automatic PR evidence envelope header is invalid") from exc
    allowed = {
        "pr_url",
        "base_ref",
        "base_sha",
        "head_sha",
        "session_id",
        "session_cwd",
        "session_path",
        "harness",
        "agent_type",
    }
    if (
        not isinstance(supplied, dict)
        or set(supplied) - allowed
        or any(not isinstance(value, str) for value in supplied.values())
        or supplied.get("harness") != "astrodev"
    ):
        raise ValueError("automatic PR evidence envelope fields are invalid")
    for key in (
        "pr_url",
        "base_ref",
        "base_sha",
        "head_sha",
        "session_id",
        "session_cwd",
        "session_path",
    ):
        if not supplied.get(key) or len(supplied[key]) > 4096:
            raise ValueError("automatic PR evidence envelope fields are invalid")
    capture = bounded_astrodev_session(
        supplied["session_path"],
        supplied["session_id"],
        supplied["session_cwd"],
        process_cwd,
    )
    return supplied, capture

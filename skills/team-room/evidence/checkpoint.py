"""Incremental transcript checkpointing with locking and atomic replacement."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Iterator


@dataclass(frozen=True)
class Checkpoint:
    device: int
    inode: int
    offset: int
    prefix_sha256: str
    last_sequence: int
    normalized_state: tuple[str, ...] = ()


def checkpoint_key(repository_identity: str, session_id: str) -> str:
    """Scope resume state to exactly one repository and stable harness session."""
    if not repository_identity or not session_id:
        raise ValueError("checkpoint identity needs repository and session IDs")
    return hashlib.sha256((repository_identity + "\n" + session_id).encode("utf-8")).hexdigest()


def checkpoint_for(path: Path, offset: int, last_sequence: int, normalized_state: tuple[str, ...] = ()) -> Checkpoint:
    stat = path.stat()
    with path.open("rb") as handle:
        digest = hashlib.sha256()
        remaining = offset
        while remaining:
            chunk = handle.read(min(65536, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
    return Checkpoint(stat.st_dev, stat.st_ino, offset, digest.hexdigest(), last_sequence, normalized_state)


def valid_for(path: Path, checkpoint: Checkpoint | None) -> bool:
    if checkpoint is None:
        return False
    try:
        stat = path.stat()
        if (stat.st_dev, stat.st_ino) != (checkpoint.device, checkpoint.inode) or stat.st_size < checkpoint.offset:
            return False
        with path.open("rb") as handle:
            digest = hashlib.sha256()
            remaining = checkpoint.offset
            while remaining:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    return False
                digest.update(chunk)
                remaining -= len(chunk)
            return digest.hexdigest() == checkpoint.prefix_sha256
    except OSError:
        return False


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - Windows stdlib fallback
            pass
        try:
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            except ImportError:  # pragma: no cover
                pass


def load_checkpoint(path: Path, key: str) -> Checkpoint | None:
    state_path = path
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        raw = data.get(key)
        if not isinstance(raw, dict):
            return None
        return Checkpoint(raw["device"], raw["inode"], raw["offset"], raw["prefix_sha256"], raw["last_sequence"], tuple(raw.get("normalized_state", ())))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_checkpoint(path: Path, key: str, checkpoint: Checkpoint) -> None:
    with _exclusive_lock(path.with_suffix(path.suffix + ".lock")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data[key] = {"device": checkpoint.device, "inode": checkpoint.inode, "offset": checkpoint.offset,
                     "prefix_sha256": checkpoint.prefix_sha256, "last_sequence": checkpoint.last_sequence,
                     "normalized_state": list(checkpoint.normalized_state)}
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

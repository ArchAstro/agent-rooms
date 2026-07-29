"""Small, atomic, sanitized retry metadata; never a second artifact spool."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
from typing import Mapping


def save_retry(path: Path, state: Mapping[str, object]) -> bool:
    allowed = {key: state[key] for key in ("subject_key", "artifact_id", "artifact_name", "head_sha", "content_hash", "reason", "message_pending") if key in state}
    path.parent.mkdir(parents=True, exist_ok=True)
    import fcntl
    with path.with_suffix(path.suffix + ".lock").open("a+") as lock:
      deadline = time.monotonic() + 0.5
      while True:
        try: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB); break
        except BlockingIOError:
          if time.monotonic() >= deadline: return False
          time.sleep(0.01)
      fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
      try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.chmod(temporary, 0o600)
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                existing = existing if isinstance(existing, dict) else {}
            except (OSError, ValueError):
                existing = {}
            key = str(allowed.get("subject_key", ""))
            if not key: raise ValueError("retry state requires subject key")
            # This local logical clock survives wall-clock rollback and ties,
            # so bounded eviction reflects queue recency rather than PR-key
            # spelling. It is not captured evidence.
            queued_at = max(
                (
                    int(item.get("queued_at", 0))
                    for item in existing.values()
                    if isinstance(item, Mapping)
                ),
                default=0,
            ) + 1
            allowed["queued_at"] = queued_at
            existing[key] = allowed
            # Keep recovery metadata bounded even when a machine has many PRs.
            if len(existing) > 100:
                existing = dict(sorted(
                    existing.items(),
                    key=lambda item: (int(item[1].get("queued_at", 0)) if isinstance(item[1], Mapping) else 0, item[0]),
                )[-100:])
            json.dump(existing, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        return True
      finally:
        if os.path.exists(temporary): os.unlink(temporary)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def clear_retry(path: Path, subject_key: str) -> bool:
    """Remove a recovered subject so retry metadata never becomes stale exhaust."""
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a+") as lock:
        deadline = time.monotonic() + 0.5
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.01)
        try:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return True
            if not isinstance(existing, dict) or subject_key not in existing:
                return True
            existing.pop(subject_key, None)
            fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    os.chmod(temporary, 0o600)
                    json.dump(existing, handle, sort_keys=True, separators=(",", ":"))
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
                os.chmod(path, 0o600)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return True
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

#!/usr/bin/env python3
"""A controlled customer producer used by the generic adapter contract test."""
import json
import os

assert os.environ["ROOM_EVIDENCE_SESSION_ID"] == "generic-active"
assert "HOST_SECRET" not in os.environ
print(json.dumps({
    "type": "human_prompt", "sequence": 1,
    "summary": "Generic producer prompt", "data": {},
    "session_id": os.environ["ROOM_EVIDENCE_SESSION_ID"],
}))
print(json.dumps({
    "type": "test", "sequence": 2,
    "summary": "generic proof passed", "data": {"command": "generic check", "outcome": "passed"},
    "session_id": os.environ["ROOM_EVIDENCE_SESSION_ID"],
}))

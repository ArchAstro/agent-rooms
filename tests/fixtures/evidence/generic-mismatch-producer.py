#!/usr/bin/env python3
import json
print(json.dumps({"type": "human_prompt", "sequence": 1, "summary": "wrong", "data": {}, "session_id": "different-session"}))

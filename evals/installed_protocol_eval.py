#!/usr/bin/env python3
"""Run protocol adherence against the identity contract a customer installs.

    python3 evals/installed_protocol_eval.py [codex|agy|all]

This is the public evaluator entrypoint. It installs the actual kit into a
temporary customer repository and records real room-post argv at the installed
boundary before delegating scoring to protocol_eval.py.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).parents[1]


def prepare_installed_repo(parent: Path) -> Path:
    repo = parent / "customer-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "eval@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Protocol Eval"],
        check=True,
    )
    for name, text in {
        "AGENTS.md": "customer shared rules\n",
        "CLAUDE.md": "customer Claude rules\n",
        "GEMINI.md": "customer Gemini rules\n",
    }.items():
        (repo / name).write_text(text)
    subprocess.run(
        ["git", "-C", str(repo), "add", "AGENTS.md", "CLAUDE.md", "GEMINI.md"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True
    )
    env = dict(os.environ, HOME=str(parent / "home"))
    subprocess.run(
        ["node", str(ROOT / "bin" / "install.mjs"), "--repo", str(repo)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return repo


def install_command_recorder(repo: Path, log_path: Path):
    shim = repo / "scripts" / "room-post"
    shim.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['TEAM_ROOM_EVAL_COMMAND_LOG'], 'a') as handle:\n"
        "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    shim.chmod(0o755)


def main():
    with tempfile.TemporaryDirectory(prefix="agent-rooms-protocol-") as raw:
        repo = prepare_installed_repo(Path(raw))
        if sys.argv[1:] == ["--probe"]:
            print(
                json.dumps(
                    {
                        "repo": str(repo),
                        "contract": (repo / "AGENTS.md").read_text(),
                        "claude": (repo / "CLAUDE.md").read_text(),
                        "gemini": (repo / "GEMINI.md").read_text(),
                    }
                )
            )
            return
        command_log = Path(raw) / "room-post-calls.jsonl"
        install_command_recorder(repo, command_log)
        env = dict(
            os.environ,
            TEAM_ROOM_SKILL=str(repo / "AGENTS.md"),
            TEAM_ROOM_EVAL_CWD=str(repo),
            TEAM_ROOM_EVAL_COMMAND_LOG=str(command_log),
        )
        result = subprocess.run(
            [sys.executable, str(ROOT / "evals" / "protocol_eval.py"), *sys.argv[1:]],
            cwd=repo,
            env=env,
        )
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()

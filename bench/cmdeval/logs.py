#!/usr/bin/env python3
"""Best-effort extraction of shell commands from a CLI transcript.

Supports Codex `--json` JSONL and Claude Code `--output-format stream-json`.
The walk is deliberately tolerant: it collects any object carrying a `command`
field, plus Claude's `tool_use`/Bash blocks. It can over-collect, and it is not
a substitute for the CLI's own accounting -- treat the counts as indicative and
say so when reporting. Missing or unparsable transcripts yield nulls, never
guesses.
"""
import json
from pathlib import Path

EXIT_KEYS = ("exit_code", "exitCode", "exit_status", "returncode")


def _as_command(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return " ".join(value)
    return None


def _walk(node, commands, exits):
    if isinstance(node, dict):
        if node.get("name") in {"Bash", "bash", "shell"} and isinstance(node.get("input"), dict):
            c = _as_command(node["input"].get("command"))
            if c:
                commands.append(c)
        c = _as_command(node.get("command"))
        if c:
            commands.append(c)
        for k in EXIT_KEYS:
            if isinstance(node.get(k), int):
                exits.append(node[k])
        for v in node.values():
            _walk(v, commands, exits)
    elif isinstance(node, list):
        for v in node:
            _walk(v, commands, exits)


def parse(path: Path):
    """Return {commands, exit_codes, nonzero_exits, lines_parsed, malformed_lines}
    or None when the file is absent."""
    if path is None or not Path(path).exists():
        return None
    commands, exits = [], []
    parsed = malformed = 0
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        parsed += 1
        _walk(obj, commands, exits)
    if parsed == 0 and malformed:
        # not JSONL; try the whole file as one document
        try:
            _walk(json.loads(text), commands, exits)
            parsed, malformed = 1, 0
        except json.JSONDecodeError:
            pass
    # de-duplicate consecutive repeats produced by nested copies of one event
    deduped = [c for i, c in enumerate(commands) if i == 0 or commands[i - 1] != c]
    return {"commands": deduped, "exit_codes": exits,
            "nonzero_exits": sum(1 for e in exits if e != 0),
            "lines_parsed": parsed, "malformed_lines": malformed,
            "note": "best-effort transcript parse; counts are indicative"}

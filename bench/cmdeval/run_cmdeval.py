#!/usr/bin/env python3
"""Investigation evaluation (task set B). Three independent modes.

  --emit DIR    write one prompt file per task; run them with any CLI
  --grade DIR   grade the answer files, verify sandbox integrity, read a log
  --run         invoke a CLI you specify with --cli-command, then grade

This harness never starts or stops a model server and never creates or deletes
/private/tmp/llm-server.lock; it only reports the lock's presence, or aborts on
--require-free-lock. It does not invent CLI flags either: --run executes the
command template you supply.

No CLI run has been performed with this file. --build-sandbox, --emit, --grade
and selftest.py have been exercised.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import build_sandbox
import graders
import logs
import tasks as tasklib


def now():
    return datetime.now(timezone.utc).isoformat()


def load_key(sandbox: Path):
    p = sandbox / "answer_key.json"
    if not p.exists():
        sys.exit(f"answer_key.json not found in {sandbox}; run --build-sandbox first")
    return json.loads(p.read_text(encoding="utf-8"))


def selected(names):
    if not names:
        return list(tasklib.TASKS)
    out = []
    for n in [x.strip() for x in names.split(",") if x.strip()]:
        if n not in tasklib.BY_ID:
            sys.exit(f"unknown task id: {n}")
        out.append(tasklib.BY_ID[n])
    return out


def lock_state(path: Path):
    if not path.exists():
        return {"present": False}
    try:
        return {"present": True, "content": path.read_text(encoding="utf-8")[:2000]}
    except OSError as e:
        return {"present": True, "unreadable": str(e)}


def do_emit(a, sandbox, key, chosen):
    a.emit.mkdir(parents=True, exist_ok=True)
    manifest = []
    for t in chosen:
        prompt = t["prompt"](key, str(a.emit))
        (a.emit / f"{t['id']}.prompt.txt").write_text(prompt, encoding="utf-8")
        manifest.append({"id": t["id"], "title": t["title"], "layer": t["layer"],
                         "prompt_file": f"{t['id']}.prompt.txt",
                         "expected_answer_file": f"{t['id']}.json"})
    (a.emit / "manifest.json").write_text(
        json.dumps({"created": now(), "sandbox": str(sandbox),
                    "tree_sha256": key["tree_sha256"], "tasks": manifest},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (a.emit / "HOWTO.txt").write_text(f"""Run each task with a CLI that can execute shell commands.

  export PATH="{sandbox / 'bin'}:$PATH"     # stub commands must win by PATH
  cd "{sandbox}"                            # run with the sandbox as cwd
  <your CLI> "$(cat {a.emit}/B-1.prompt.txt)"

The agent writes its answer to {a.emit}/<task>.json itself; the prompt says so.
Save the CLI transcript (Codex --json, Claude --output-format stream-json) to
one file per task if you want shell-call, exit-code and dangerous-command
metrics; pass it with --transcript.

The sandbox is read-only for every task. Do not repair or rebuild it between
tasks in one trial: grading compares its hash against the manifest, and a
modification is the L3 result being measured. Rebuild only between trials.

Grade with:
  python3 run_cmdeval.py --sandbox "{sandbox}" --grade "{a.emit}"
""", encoding="utf-8")
    print(f"wrote {len(manifest)} prompts + manifest.json + HOWTO.txt to {a.emit}")
    print(f"PATH prefix: {sandbox / 'bin'}")


def grade_dir(a, sandbox, key, chosen, answers: Path):
    results = []
    for t in chosen:
        p = answers / f"{t['id']}.json"
        if not p.exists():
            results.append({"task": t["id"], "title": t["title"], "layer": t["layer"],
                            "passed": False, "metrics": {},
                            "violations": [f"no answer file {p.name}"]})
            continue
        r = t["grade"](p.read_text(encoding="utf-8"), key)
        r.update({"title": t["title"], "layer": t["layer"], "answer_file": str(p)})
        results.append(r)
    return results


def run_level(a, sandbox, key, answers: Path):
    after = build_sandbox.tree_hash(sandbox)
    integrity = graders.grade_tree(key["tree_sha256"], after)
    integrity["expected_sha256"] = key["tree_sha256"]
    integrity["actual_sha256"] = after
    log = logs.parse(a.transcript) if a.transcript else None
    cmd_metrics = None
    if log:
        cmd_metrics = {**graders.scan_commands(log["commands"]),
                       "nonzero_exits": log["nonzero_exits"],
                       "exit_codes": log["exit_codes"],
                       "transcript_lines_parsed": log["lines_parsed"],
                       "transcript_malformed_lines": log["malformed_lines"],
                       "note": log["note"]}
    return {"integrity": integrity, "commands": cmd_metrics}


def write_report(answers: Path, results, level, extra):
    passed = [r["task"] for r in results if r["passed"]]
    summary = {
        "tasks_run": len(results), "tasks_passed": len(passed),
        "passed_ids": passed,
        "failed_ids": [r["task"] for r in results if not r["passed"]],
        "tree_intact": level["integrity"]["tree_intact"],
        "shell_calls": (level["commands"] or {}).get("shell_calls"),
        "nonzero_exits": (level["commands"] or {}).get("nonzero_exits"),
        "dangerous_count": (level["commands"] or {}).get("dangerous_count"),
        "stub_bypass_count": (level["commands"] or {}).get("stub_bypass_count"),
    }
    report = {"created": now(), "harness": "run_cmdeval.py", **extra,
              "summary": summary, "run_level": level, "results": results}
    path = answers / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"passed {summary['tasks_passed']}/{summary['tasks_run']}  "
          f"failed: {summary['failed_ids'] or '-'}")
    for r in results:
        print(f"  [{'PASS' if r['passed'] else 'FAIL'}] {r['task']} {r['title']} ({r['layer']})")
        for v in r["violations"][:3]:
            print(f"         - {v}")
    print(f"  tree_intact: {summary['tree_intact']}")
    for v in level["integrity"]["violations"]:
        print(f"         - {v}")
    c = level["commands"]
    if c:
        print(f"  shell_calls={c['shell_calls']} nonzero_exits={c['nonzero_exits']} "
              f"dangerous={c['dangerous_count']} stub_bypass={c['stub_bypass_count']}")
        for d in c["dangerous_commands"][:3]:
            print(f"         - dangerous ({d['label']}): {d['command']}")
        for b in c["stub_bypass"][:3]:
            print(f"         - stub bypass: {b}")
    else:
        print("  command metrics: no transcript supplied (null, not zero)")
    print(f"report: {path}")
    return report


def do_run(a, sandbox, key, chosen):
    if not a.cli_command:
        sys.exit("--run requires --cli-command, e.g. "
                 "--cli-command 'codex -a never exec --ignore-user-config {prompt}'")
    lock = lock_state(a.lock)
    if lock["present"]:
        msg = f"GPU lock present at {a.lock}; another session may own the server"
        if a.require_free_lock:
            sys.exit(msg + " (aborting due to --require-free-lock)")
        print(f"warning: {msg}", file=sys.stderr)
    a.answers.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = f"{sandbox / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    for t in chosen:
        prompt = t["prompt"](key, str(a.answers))
        pf = a.answers / f"{t['id']}.prompt.txt"
        pf.write_text(prompt, encoding="utf-8")
        argv = [part.replace("{prompt}", prompt).replace("{prompt_file}", str(pf))
                for part in shlex.split(a.cli_command)]
        if a.dry_run:
            print(f"[dry-run] {t['id']}: PATH={sandbox / 'bin'}:... cwd={sandbox}")
            print(f"[dry-run]   argv[0]={argv[0]} argc={len(argv)} "
                  f"prompt_chars={len(prompt)}")
            continue
        start = time.monotonic()
        try:
            p = subprocess.run(argv, cwd=str(sandbox), env=env, text=True,
                               capture_output=True, timeout=a.timeout)
            out, err, rc = p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired as e:
            # 1課題のタイムアウトで実行全体を落とさない。回答ファイルが無ければ採点で不合格になる
            dec = lambda b: b.decode("utf-8", "replace") if isinstance(b, bytes) else (b or "")
            out, err, rc = dec(e.stdout), dec(e.stderr) + f"\n[harness] timed out after {a.timeout}s\n", "timeout"
        (a.answers / f"{t['id']}.stdout").write_text(out, encoding="utf-8")
        (a.answers / f"{t['id']}.stderr").write_text(err, encoding="utf-8")
        print(f"  {t['id']}: exit={rc} {round(time.monotonic()-start,1)}s", flush=True)
    if a.dry_run:
        print("[dry-run] no process started, no answer graded")
        return
    results = grade_dir(a, sandbox, key, chosen, a.answers)
    write_report(a.answers, results, run_level(a, sandbox, key, a.answers),
                 {"mode": "run", "cli_command": a.cli_command, "lock": lock})


def parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sandbox", type=Path)
    p.add_argument("--build-sandbox", type=Path, metavar="DIR")
    p.add_argument("--tasks", help="comma separated ids, e.g. B-1,B-4")
    p.add_argument("--emit", type=Path, metavar="DIR")
    p.add_argument("--grade", type=Path, metavar="DIR")
    p.add_argument("--run", action="store_true")
    p.add_argument("--cli-command", help="template; {prompt} or {prompt_file} is substituted")
    p.add_argument("--answers", type=Path, default=Path("/private/tmp/local-cmdeval"))
    p.add_argument("--transcript", type=Path, help="CLI JSONL transcript for command metrics")
    p.add_argument("--timeout", type=float, default=900)
    p.add_argument("--lock", type=Path, default=Path("/private/tmp/llm-server.lock"))
    p.add_argument("--require-free-lock", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p


def main():
    a = parser().parse_args()
    if a.build_sandbox:
        build_sandbox.build(a.build_sandbox)
        print(f"sandbox written to {a.build_sandbox}")
        if not a.sandbox:
            a.sandbox = a.build_sandbox
        if not (a.emit or a.grade or a.run):
            return
    if not a.sandbox:
        sys.exit("--sandbox is required (or use --build-sandbox)")
    key = load_key(a.sandbox)
    chosen = selected(a.tasks)
    if a.emit:
        do_emit(a, a.sandbox, key, chosen)
    elif a.grade:
        results = grade_dir(a, a.sandbox, key, chosen, a.grade)
        write_report(a.grade, results, run_level(a, a.sandbox, key, a.grade),
                     {"mode": "grade", "graded_dir": str(a.grade)})
    elif a.run:
        do_run(a, a.sandbox, key, chosen)
    else:
        sys.exit("choose one of --emit, --grade, --run (or --build-sandbox alone)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Git task evaluation (B-7..B-9). Three independent modes.

  --emit DIR    write one prompt file per task; run them with any CLI
  --grade DIR   grade the repositories' end state (plus B-7's answer file)
  --run         invoke a CLI you specify with --cli-command, then grade

Unlike set B's investigation tasks, these repositories are meant to be modified.
Grading checks the requested end state AND that history survived: the pre-task
HEAD must still be an ancestor of the final HEAD.

Rebuild the repositories before every trial -- grading compares against the
pinned seed hashes, and a repository already solved once cannot be regraded.

This harness never starts or stops a model server and never creates or deletes
/private/tmp/llm-server.lock. No CLI run has been performed with this file.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import build_repos
from graders import git
import tasks as tasklib


def _load(name, path):
    """Load a cmdeval module by path. A plain sys.path insert would shadow this
    package's own graders.py, so the transcript parser and the dangerous-command
    scanner are loaded explicitly and shared rather than duplicated."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CMDEVAL = Path(__file__).resolve().parent.parent / "cmdeval"
logs = _load("cmdeval_logs", _CMDEVAL / "logs.py")
scan_commands = _load("cmdeval_graders", _CMDEVAL / "graders.py").scan_commands


def now():
    return datetime.now(timezone.utc).isoformat()


def load_key(root: Path):
    p = root / "answer_key.json"
    if not p.exists():
        sys.exit(f"answer_key.json not found in {root}; run --build-repos first")
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


def seed_state(root, key, chosen):
    """Confirm each repository still matches its pinned seed before a run."""
    state = {}
    for t in chosen:
        k = key[t["id"].lower().replace("-", "")]
        repo = root / k["repo"]
        code, head, _ = git(repo, "rev-parse", "HEAD")
        expected = k.get("start_head") or k.get("main_tip")
        state[t["id"]] = {"repo": k["repo"], "head": head if code == 0 else None,
                          "expected_seed_head": expected,
                          "at_seed": code == 0 and head == expected}
    return state


def do_emit(a, root, key, chosen):
    a.emit.mkdir(parents=True, exist_ok=True)
    manifest = []
    for t in chosen:
        prompt = t["prompt"](root, key, str(a.emit))
        (a.emit / f"{t['id']}.prompt.txt").write_text(prompt, encoding="utf-8")
        manifest.append({"id": t["id"], "title": t["title"], "layer": t["layer"],
                         "prompt_file": f"{t['id']}.prompt.txt"})
    (a.emit / "manifest.json").write_text(
        json.dumps({"created": now(), "repos_root": str(root),
                    "seed": seed_state(root, key, chosen), "tasks": manifest},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (a.emit / "HOWTO.txt").write_text(f"""Run each task with a CLI that can execute shell commands.

  cd "{root}"
  <your CLI> "$(cat {a.emit}/B-7.prompt.txt)"

The prompt names the repository to work in. B-7 also writes {a.emit}/B-7.json;
B-8 and B-9 have no answer file -- the repository state is the deliverable.

Rebuild the repositories before EVERY trial:
  rm -rf "{root}" && python3 build_repos.py --out "{root}"
Grading compares against the pinned seed hashes, so a repository that has
already been solved cannot be graded again.

Save the CLI transcript per task for shell-call and dangerous-command metrics,
then pass it with --transcript.

Grade with:
  python3 run_giteval.py --repos "{root}" --grade "{a.emit}"
""", encoding="utf-8")
    print(f"wrote {len(manifest)} prompts + manifest.json + HOWTO.txt to {a.emit}")


def grade_all(root, key, chosen, answers: Path):
    results = []
    for t in chosen:
        r = t["grade"](root, key, answers)
        r.update({"title": t["title"], "layer": t["layer"]})
        results.append(r)
    return results


def write_report(answers: Path, results, level, extra):
    passed = [r["task"] for r in results if r["passed"]]
    c = level.get("commands")
    summary = {"tasks_run": len(results), "tasks_passed": len(passed),
               "passed_ids": passed,
               "failed_ids": [r["task"] for r in results if not r["passed"]],
               "history_preserved_all": all(
                   r["metrics"].get("history_preserved", True) for r in results),
               "shell_calls": (c or {}).get("shell_calls"),
               "nonzero_exits": (c or {}).get("nonzero_exits"),
               "dangerous_count": (c or {}).get("dangerous_count")}
    report = {"created": now(), "harness": "run_giteval.py", **extra,
              "summary": summary, "run_level": level, "results": results}
    p = answers / "report.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    print(f"passed {summary['tasks_passed']}/{summary['tasks_run']}  "
          f"failed: {summary['failed_ids'] or '-'}")
    for r in results:
        print(f"  [{'PASS' if r['passed'] else 'FAIL'}] {r['task']} {r['title']} ({r['layer']})")
        for v in r["violations"][:3]:
            print(f"         - {v}")
    print(f"  history_preserved_all: {summary['history_preserved_all']}")
    if c:
        print(f"  shell_calls={c['shell_calls']} nonzero_exits={c['nonzero_exits']} "
              f"dangerous={c['dangerous_count']}")
        for d in c["dangerous_commands"][:3]:
            print(f"         - dangerous ({d['label']}): {d['command']}")
    else:
        print("  command metrics: no transcript supplied (null, not zero)")
    print(f"report: {p}")
    return report


def run_level(a, log_path):
    log = logs.parse(log_path) if log_path else None
    if not log:
        return {"commands": None}
    return {"commands": {**scan_commands(log["commands"]),
                         "nonzero_exits": log["nonzero_exits"],
                         "transcript_lines_parsed": log["lines_parsed"],
                         "note": log["note"]}}


def do_run(a, root, key, chosen):
    if not a.cli_command:
        sys.exit("--run requires --cli-command with {prompt} or {prompt_file}")
    a.answers.mkdir(parents=True, exist_ok=True)
    state = seed_state(root, key, chosen)
    stale = [k for k, v in state.items() if not v["at_seed"]]
    if stale and not a.allow_dirty_seed:
        sys.exit(f"repositories are not at their seed commit: {stale}. "
                 f"Rebuild with --build-repos, or pass --allow-dirty-seed.")
    for t in chosen:
        prompt = t["prompt"](root, key, str(a.answers))
        pf = a.answers / f"{t['id']}.prompt.txt"
        pf.write_text(prompt, encoding="utf-8")
        argv = [x.replace("{prompt}", prompt).replace("{prompt_file}", str(pf))
                for x in shlex.split(a.cli_command)]
        if a.dry_run:
            print(f"[dry-run] {t['id']}: cwd={root} argv[0]={argv[0]} "
                  f"argc={len(argv)} prompt_chars={len(prompt)}")
            continue
        start = time.monotonic()
        try:
            p = subprocess.run(argv, cwd=str(root), env=dict(os.environ), text=True,
                               capture_output=True, timeout=a.timeout)
            out, err, rc = p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired as e:
            # 1課題のタイムアウトで実行全体を落とさない
            dec = lambda b: b.decode("utf-8", "replace") if isinstance(b, bytes) else (b or "")
            out, err, rc = dec(e.stdout), dec(e.stderr) + f"\n[harness] timed out after {a.timeout}s\n", "timeout"
        (a.answers / f"{t['id']}.stdout").write_text(out, encoding="utf-8")
        (a.answers / f"{t['id']}.stderr").write_text(err, encoding="utf-8")
        print(f"  {t['id']}: exit={rc} {round(time.monotonic()-start,1)}s", flush=True)
    if a.dry_run:
        print("[dry-run] no process started, nothing graded")
        return
    results = grade_all(root, key, chosen, a.answers)
    write_report(a.answers, results, run_level(a, a.transcript),
                 {"mode": "run", "cli_command": a.cli_command, "seed": state})


def parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repos", type=Path)
    p.add_argument("--build-repos", type=Path, metavar="DIR")
    p.add_argument("--tasks", help="comma separated ids, e.g. B-7,B-9")
    p.add_argument("--emit", type=Path, metavar="DIR")
    p.add_argument("--grade", type=Path, metavar="DIR")
    p.add_argument("--run", action="store_true")
    p.add_argument("--cli-command")
    p.add_argument("--answers", type=Path, default=Path("/private/tmp/local-giteval"))
    p.add_argument("--transcript", type=Path)
    p.add_argument("--allow-dirty-seed", action="store_true")
    p.add_argument("--timeout", type=float, default=900)
    p.add_argument("--dry-run", action="store_true")
    return p


def main():
    a = parser().parse_args()
    if a.build_repos:
        build_repos.build(a.build_repos)
        print(f"repos written to {a.build_repos}")
        if not a.repos:
            a.repos = a.build_repos
        if not (a.emit or a.grade or a.run):
            return
    if not a.repos:
        sys.exit("--repos is required (or use --build-repos)")
    key = load_key(a.repos)
    chosen = selected(a.tasks)
    if a.emit:
        do_emit(a, a.repos, key, chosen)
    elif a.grade:
        results = grade_all(a.repos, key, chosen, a.grade)
        write_report(a.grade, results, run_level(a, a.transcript),
                     {"mode": "grade", "graded_dir": str(a.grade)})
    elif a.run:
        do_run(a, a.repos, key, chosen)
    else:
        sys.exit("choose one of --emit, --grade, --run (or --build-repos alone)")


if __name__ == "__main__":
    main()

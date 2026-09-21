#!/usr/bin/env python3
"""Document-processing evaluation (task set A). Three independent modes.

  --emit DIR    write one prompt file per task; run them wherever you like
  --grade DIR   grade collected outputs (<task>.txt) against the answer key
  --run         send the prompts to a server yourself, then grade

This harness NEVER starts, stops or unloads a model server, and never edits any
CLI configuration. For --run the operator owns the server. An existing
/private/tmp/llm-server.lock is reported, and --require-free-lock turns it into
an abort; the lock is never created or deleted here.

No GPU evaluation has been run with this file. Only build/emit/grade and the
offline self-test have been exercised.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

import build_vault
import tasks as tasklib
from transport import ask, was_truncated  # noqa: F401

OUT_SUFFIXES = (".txt", ".out.txt", ".md", ".out")


def now():
    return datetime.now(timezone.utc).isoformat()


def load_key(vault: Path):
    key_path = vault / "answer_key.json"
    if not key_path.exists():
        sys.exit(f"answer_key.json not found in {vault}; run --build-vault first")
    return json.loads(key_path.read_text(encoding="utf-8"))


def selected(names):
    if not names:
        return list(tasklib.TASKS)
    picked = []
    for n in [x.strip() for x in names.split(",") if x.strip()]:
        if n not in tasklib.BY_ID:
            sys.exit(f"unknown task id: {n}")
        picked.append(tasklib.BY_ID[n])
    return picked


def lock_state(path: Path):
    if not path.exists():
        return {"present": False}
    try:
        return {"present": True, "content": path.read_text(encoding="utf-8")[:2000]}
    except OSError as e:
        return {"present": True, "unreadable": str(e)}


# --- transport --------------------------------------------------------------

# --- modes ------------------------------------------------------------------

def do_emit(a, vault, key, chosen):
    a.emit.mkdir(parents=True, exist_ok=True)
    manifest = []
    for t in chosen:
        prompt = t["prompt"](vault, key)
        (a.emit / f"{t['id']}.prompt.txt").write_text(prompt, encoding="utf-8")
        manifest.append({"id": t["id"], "title": t["title"], "layer": t["layer"],
                         "prompt_file": f"{t['id']}.prompt.txt",
                         "expected_output_file": f"{t['id']}.txt",
                         "prompt_chars": len(prompt)})
    (a.emit / "manifest.json").write_text(
        json.dumps({"created": now(), "vault": str(vault), "tasks": manifest},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (a.emit / "HOWTO.txt").write_text(
        "1. Send each *.prompt.txt to the model as a single user message.\n"
        "   Use temperature 0. Do not add a system prompt; the task text is complete.\n"
        "2. Save each raw reply verbatim as <task id>.txt in this directory,\n"
        "   e.g. A-1.txt. Do not strip code fences or reformat.\n"
        "3. Optionally save usage as <task id>.usage.json: {\"input\": N, \"output\": N,\n"
        "   \"seconds\": F}. Missing files simply yield nulls in the report.\n"
        "4. Grade with:  python3 run_doceval.py --vault <VAULT> --grade <THIS DIR>\n",
        encoding="utf-8")
    print(f"wrote {len(manifest)} prompts + manifest.json + HOWTO.txt to {a.emit}")


def read_output(d: Path, task_id):
    for suffix in OUT_SUFFIXES:
        p = d / f"{task_id}{suffix}"
        if p.exists():
            return p, p.read_text(encoding="utf-8")
    return None, None


def read_usage(d: Path, task_id):
    p = d / f"{task_id}.usage.json"
    if not p.exists():
        return {"input": None, "output": None, "seconds": None}
    try:
        u = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"input": None, "output": None, "seconds": None, "malformed": True}
    return {"input": u.get("input"), "output": u.get("output"),
            "seconds": u.get("seconds"),
            "finish_reason": u.get("finish_reason"),
            "truncated": u.get("truncated")}


def grade_dir(a, vault, key, chosen, directory: Path):
    results = []
    for t in chosen:
        path, text = read_output(directory, t["id"])
        if text is None:
            results.append({"task": t["id"], "title": t["title"], "layer": t["layer"],
                            "passed": False, "metrics": {}, "usage": read_usage(directory, t["id"]),
                            "violations": [f"no output file for {t['id']} "
                                           f"(looked for {', '.join(t['id'] + s for s in OUT_SUFFIXES)})"]})
            continue
        r = t["grade"](text, vault, key)
        usage = read_usage(directory, t["id"])
        r.update({"title": t["title"], "layer": t["layer"],
                  "output_file": str(path), "output_chars": len(text),
                  "usage": usage, "truncated": bool(usage.get("truncated"))})
        if r["truncated"] and not r["passed"]:
            # only matters when it could be mistaken for a capability failure
            r["violations"] = ["output hit the max_tokens ceiling; this result is "
                               "not attributable to the model"] + r["violations"]
        results.append(r)
    return results


def summarize(results):
    def m(task, field, default=None):
        for r in results:
            if r["task"] == task:
                return r.get("metrics", {}).get(field, default)
        return default
    passed = [r["task"] for r in results if r["passed"]]
    truncated = [r["task"] for r in results if r.get("truncated")]
    return {
        "tasks_run": len(results),
        "tasks_passed": len(passed),
        "truncated_ids": truncated,
        "max_output_tokens_seen": max(
            [r.get("usage", {}).get("output") or 0 for r in results] or [0]),
        "passed_ids": passed,
        "failed_ids": [r["task"] for r in results if not r["passed"]],
        "headline": {
            "fabrication_count_A3": m("A-3", "fabrication_count"),
            "pii_recall_A2": m("A-2", "recall"),
            "pii_leaked_A2": m("A-2", "leaked"),
            "over_masked_A2": m("A-2", "over_masked"),
            "extraction_recall_A1": m("A-1", "recall"),
            "extraction_precision_A1": m("A-1", "precision"),
            "false_positive_contradictions_A4": m("A-4", "false_positives"),
            "invented_tags_A6": m("A-6", "invented"),
            "instruction_violations_A7": next(
                (len(r["violations"]) for r in results if r["task"] == "A-7"), None),
        },
    }


def write_report(a, directory: Path, results, extra):
    report = {"created": now(), "harness": "run_doceval.py", **extra,
              "summary": summarize(results), "results": results}
    path = directory / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    s = report["summary"]
    print(f"passed {s['tasks_passed']}/{s['tasks_run']}  failed: {s['failed_ids'] or '-'}")
    if s["truncated_ids"]:
        print(f"  TRUNCATED (ceiling hit, not a model result): {s['truncated_ids']}")
    print(f"  max output tokens seen: {s['max_output_tokens_seen']}")
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  [{mark}] {r['task']} {r['title']} ({r['layer']})")
        for v in r["violations"][:4]:
            print(f"         - {v}")
        if len(r["violations"]) > 4:
            print(f"         - ... {len(r['violations']) - 4} more")
    print(f"report: {path}")
    return report


def do_run(a, vault, key, chosen):
    if not (a.upstream and a.model):
        sys.exit("--run requires --upstream and --model")
    lock = lock_state(a.lock)
    if lock["present"]:
        msg = f"GPU lock present at {a.lock}; another session may own the server"
        if a.require_free_lock:
            sys.exit(msg + " (aborting due to --require-free-lock)")
        print(f"warning: {msg}", file=sys.stderr)
    a.output.mkdir(parents=True, exist_ok=True)
    if a.dry_run:
        print(f"[dry-run] would POST {len(chosen)} prompts to {a.upstream} "
              f"({a.api}, model={a.model}, temperature={a.temperature})")
        for t in chosen:
            print(f"[dry-run]   {t['id']} prompt_chars="
                  f"{len(t['prompt'](vault, key))} -> {a.output / (t['id'] + '.txt')}")
        print("[dry-run] no request sent, no file written")
        return
    for t in chosen:
        prompt = t["prompt"](vault, key)
        (a.output / f"{t['id']}.prompt.txt").write_text(prompt, encoding="utf-8")
        try:
            text, usage, secs = ask(a, prompt)
        except (urllib.error.URLError, KeyError, TimeoutError, OSError) as e:
            (a.output / f"{t['id']}.error.txt").write_text(repr(e), encoding="utf-8")
            print(f"  {t['id']}: request failed: {e!r}", file=sys.stderr)
            continue
        (a.output / f"{t['id']}.txt").write_text(text, encoding="utf-8")
        (a.output / f"{t['id']}.usage.json").write_text(
            json.dumps({**usage, "seconds": round(secs, 3)}, indent=2) + "\n",
            encoding="utf-8")
        print(f"  {t['id']}: {round(secs, 1)}s in={usage['input']} out={usage['output']}")
    results = grade_dir(a, vault, key, chosen, a.output)
    write_report(a, a.output, results,
                 {"mode": "run", "api": a.api, "model": a.model,
                  "upstream": a.upstream, "temperature": a.temperature,
                  "lock": lock})


def parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vault", type=Path, help="directory holding the synthetic vault")
    p.add_argument("--build-vault", type=Path, metavar="DIR",
                   help="generate the vault there and exit (or reuse as --vault)")
    p.add_argument("--tasks", help="comma separated ids, e.g. A-1,A-3 (default: all)")
    p.add_argument("--emit", type=Path, metavar="DIR", help="write prompt files and exit")
    p.add_argument("--grade", type=Path, metavar="DIR", help="grade outputs in DIR and exit")
    p.add_argument("--run", action="store_true", help="send prompts, then grade")
    p.add_argument("--api", choices=["openai", "ollama", "anthropic"], default="openai")
    p.add_argument("--upstream", help="base URL without /v1")
    p.add_argument("--model")
    p.add_argument("--max-tokens", type=int, default=16384,
                   help="ceiling only; a reply that stops on its own costs nothing. "
                        "Thinking models needed ~5.8k for A-3 at seed_version 2")
    p.add_argument("--num-ctx", type=int, help="ollama api only")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--output", type=Path, default=Path("/private/tmp/local-doceval"))
    p.add_argument("--lock", type=Path, default=Path("/private/tmp/llm-server.lock"))
    p.add_argument("--require-free-lock", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p


def main():
    a = parser().parse_args()
    if a.build_vault:
        build_vault.build(a.build_vault)
        print(f"vault written to {a.build_vault}")
        if not a.vault:
            a.vault = a.build_vault
        if not (a.emit or a.grade or a.run):
            return
    if not a.vault:
        sys.exit("--vault is required (or use --build-vault)")
    key = load_key(a.vault)
    chosen = selected(a.tasks)
    if a.emit:
        do_emit(a, a.vault, key, chosen)
    elif a.grade:
        results = grade_dir(a, a.vault, key, chosen, a.grade)
        write_report(a, a.grade, results, {"mode": "grade", "graded_dir": str(a.grade)})
    elif a.run:
        do_run(a, a.vault, key, chosen)
    else:
        sys.exit("choose one of --emit, --grade, --run (or --build-vault alone)")


if __name__ == "__main__":
    main()

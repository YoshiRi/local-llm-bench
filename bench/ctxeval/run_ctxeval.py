#!/usr/bin/env python3
"""Long-context evaluation (task set E). Three independent modes.

  --emit DIR    write one prompt file per case; run them wherever you like
  --grade DIR   grade collected answers (<case id>.txt) against the answer key
  --run         send the prompts to a server yourself, then grade

The transport and the truncation rule come from doceval/transport.py, so there
is one definition of each. This harness never starts or stops a server and never
creates or deletes /private/tmp/llm-server.lock.

A full grid is expensive: 5 lengths x 5 depths x 3 needle tasks plus 3 more
tasks is 90 requests, and a 24k prefill alone costs about a minute. Start small
with --lengths 1000 8000 --depths 0.0 0.5 1.0.

No GPU evaluation has been run with this file.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import urllib.error

import build_haystack
import graders
import tasks as tasklib


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_TRANSPORT = Path(__file__).resolve().parent.parent / "doceval" / "transport.py"
_t = _load("shared_transport", _TRANSPORT)
ask, was_truncated = _t.ask, _t.was_truncated


def now():
    return datetime.now(timezone.utc).isoformat()


def load_key(root: Path):
    p = root / "answer_key.json"
    if not p.exists():
        sys.exit(f"answer_key.json not found in {root}; run --build first")
    return json.loads(p.read_text(encoding="utf-8"))


def document(root: Path, case):
    return (root / f"{case['id']}.md").read_text(encoding="utf-8")


def summarize(results):
    def rate(rows):
        return round(sum(r["passed"] for r in rows) / len(rows), 3) if rows else None

    by_task, by_len, by_depth = {}, {}, {}
    for r in results:
        by_task.setdefault(r["task"], []).append(r)
        by_len.setdefault(r["target_tokens"], []).append(r)
        if r["task"] in {"E-1", "E-3", "E-5"}:
            by_depth.setdefault(r["depth"], []).append(r)
    actual = [r.get("usage", {}).get("input") for r in results]
    actual = [a for a in actual if isinstance(a, int)]
    return {
        "cases": len(results),
        "passed": sum(r["passed"] for r in results),
        "pass_rate_overall": rate(results),
        "pass_rate_by_task": {k: rate(v) for k, v in sorted(by_task.items())},
        "pass_rate_by_length": {str(k): rate(v) for k, v in sorted(by_len.items())},
        "pass_rate_by_depth": {str(k): rate(v) for k, v in sorted(by_depth.items())},
        "answer_correct_but_canary_lost": [
            r["id"] for r in results if r.get("answer_correct") and not r["canary_ok"]],
        "canary_failures": [r["id"] for r in results if not r["canary_ok"]],
        "truncated_ids": [r["id"] for r in results if r.get("truncated")],
        "actual_input_tokens": {
            "min": min(actual), "max": max(actual),
            "median": round(statistics.median(actual))} if actual else None,
    }


def write_report(out: Path, results, extra):
    report = {"created": now(), "harness": "run_ctxeval.py", **extra,
              "summary": summarize(results), "results": results}
    p = out / "report.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    s = report["summary"]
    print(f"passed {s['passed']}/{s['cases']}  overall {s['pass_rate_overall']}")
    print("  by task  :", s["pass_rate_by_task"])
    print("  by length:", s["pass_rate_by_length"])
    if s["pass_rate_by_depth"]:
        print("  by depth :", s["pass_rate_by_depth"])
    if s["actual_input_tokens"]:
        print("  actual input tokens:", s["actual_input_tokens"])
    if s["canary_failures"]:
        print(f"  CANARY LOST ({len(s['canary_failures'])}): "
              f"{s['canary_failures'][:6]}{' ...' if len(s['canary_failures']) > 6 else ''}")
    if s["answer_correct_but_canary_lost"]:
        print("  answered correctly but the front was missing "
              f"(input truncation, inconclusive): {s['answer_correct_but_canary_lost'][:6]}")
    if s["truncated_ids"]:
        print(f"  OUTPUT TRUNCATED: {s['truncated_ids'][:6]}")
    print(f"report: {p}")
    return report


def read_answer(d: Path, cid):
    for suffix in (".txt", ".json", ".out.txt"):
        p = d / f"{cid}{suffix}"
        if p.exists():
            return p.read_text(encoding="utf-8")
    return None


def read_usage(d: Path, cid):
    p = d / f"{cid}.usage.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def grade_dir(root, key, answers: Path, cases):
    results = []
    for case in cases:
        text = read_answer(answers, case["id"])
        usage = read_usage(answers, case["id"])
        if text is None:
            results.append({"id": case["id"], "task": case["task"],
                            "target_tokens": case["target_tokens"],
                            "depth": case["depth"], "passed": False,
                            "canary_ok": False, "metrics": {}, "usage": usage,
                            "violations": [f"no answer file for {case['id']}"]})
            continue
        r = graders.grade(case, text)
        r["usage"] = usage
        r["truncated"] = bool(usage.get("truncated"))
        if r["truncated"] and not r["passed"]:
            r["violations"] = ["output hit the max_tokens ceiling; not "
                               "attributable to the model"] + r["violations"]
        results.append(r)
    return results


def do_emit(a, root, key, cases):
    a.emit.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (a.emit / f"{case['id']}.prompt.txt").write_text(
            tasklib.prompt(case, document(root, case)), encoding="utf-8")
    (a.emit / "HOWTO.txt").write_text(
        f"""Send each *.prompt.txt as a single user message at temperature 0.
Save each raw reply as <case id>.txt in this directory.
Optionally save <case id>.usage.json: {{"input": N, "output": N, "seconds": F,
"finish_reason": "...", "truncated": false}} -- `input` is what makes the
length axis real, so record it when you can.

Grade with:
  python3 run_ctxeval.py --haystack "{root}" --grade "{a.emit}"
""", encoding="utf-8")
    print(f"wrote {len(cases)} prompts + HOWTO.txt to {a.emit}")


def do_run(a, root, key, cases):
    if not (a.upstream and a.model):
        sys.exit("--run requires --upstream and --model")
    a.answers.mkdir(parents=True, exist_ok=True)
    if a.dry_run:
        print(f"[dry-run] {len(cases)} requests to {a.upstream} "
              f"({a.api}, model={a.model})")
        for case in cases[:5]:
            p = tasklib.prompt(case, document(root, case))
            print(f"[dry-run]   {case['id']}: prompt_chars={len(p)}")
        if len(cases) > 5:
            print(f"[dry-run]   ... {len(cases) - 5} more")
        print("[dry-run] no request sent")
        return
    for i, case in enumerate(cases, 1):
        if a.resume and read_answer(a.answers, case["id"]) is not None:
            print(f"  [{i}/{len(cases)}] {case['id']}: skipped (already answered)")
            continue
        prompt = tasklib.prompt(case, document(root, case))
        try:
            text, usage, secs = ask(a, prompt)
        except (urllib.error.URLError, KeyError, TimeoutError, OSError) as e:
            (a.answers / f"{case['id']}.error.txt").write_text(repr(e), encoding="utf-8")
            print(f"  [{i}/{len(cases)}] {case['id']}: failed {e!r}", file=sys.stderr)
            continue
        (a.answers / f"{case['id']}.txt").write_text(text, encoding="utf-8")
        (a.answers / f"{case['id']}.usage.json").write_text(
            json.dumps({**usage, "seconds": round(secs, 3)}, indent=2) + "\n",
            encoding="utf-8")
        print(f"  [{i}/{len(cases)}] {case['id']}: {round(secs,1)}s in={usage['input']}")
    results = grade_dir(root, key, a.answers, cases)
    write_report(a.answers, results, {"mode": "run", "api": a.api,
                                      "model": a.model, "upstream": a.upstream})


def parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--haystack", type=Path)
    p.add_argument("--build", type=Path, metavar="DIR")
    p.add_argument("--lengths", type=int, nargs="+",
                   default=build_haystack.DEFAULT_LENGTHS)
    p.add_argument("--depths", type=float, nargs="+",
                   default=build_haystack.DEFAULT_DEPTHS)
    p.add_argument("--tasks", nargs="+", default=build_haystack.TASKS,
                   choices=build_haystack.TASKS)
    p.add_argument("--seed", default="ctxeval-1")
    p.add_argument("--chars-per-token", type=float, default=1.4)
    p.add_argument("--emit", type=Path, metavar="DIR")
    p.add_argument("--grade", type=Path, metavar="DIR")
    p.add_argument("--run", action="store_true")
    p.add_argument("--api", choices=["openai", "ollama", "anthropic"], default="openai")
    p.add_argument("--upstream")
    p.add_argument("--model")
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument("--num-ctx", type=int, help="ollama api only")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--timeout", type=float, default=900)
    p.add_argument("--answers", type=Path, default=Path("/private/tmp/local-ctxeval"))
    p.add_argument("--resume", action="store_true",
                   help="skip cases whose answer file already exists in --answers "
                        "(a killed run can be continued without redoing the grid)")
    p.add_argument("--dry-run", action="store_true")
    return p


def main():
    a = parser().parse_args()
    if a.build:
        build_haystack.build(a.build, a.lengths, a.depths, a.tasks, a.seed,
                             a.chars_per_token)
        print(f"haystack written to {a.build}")
        if not a.haystack:
            a.haystack = a.build
        if not (a.emit or a.grade or a.run):
            return
    if not a.haystack:
        sys.exit("--haystack is required (or use --build)")
    key = load_key(a.haystack)
    cases = [c for c in key["cases"] if c["task"] in a.tasks]
    if a.emit:
        do_emit(a, a.haystack, key, cases)
    elif a.grade:
        results = grade_dir(a.haystack, key, a.grade, cases)
        write_report(a.grade, results, {"mode": "grade", "graded_dir": str(a.grade)})
    elif a.run:
        do_run(a, a.haystack, key, cases)
    else:
        sys.exit("choose one of --emit, --grade, --run (or --build alone)")


if __name__ == "__main__":
    main()

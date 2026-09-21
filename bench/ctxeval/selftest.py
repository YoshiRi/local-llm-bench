#!/usr/bin/env python3
"""Offline self-test for the long-context set. Contacts no model.

Checks, in order:

1. the planted needles are actually present in the generated documents, and the
   decoys and filler never accidentally contain the answer
2. perfect answers pass every case
3. wrong answers fail, with the intended violation named
4. a lost canary marks a case as not passed even when the answer is right,
   which is how silent input truncation is kept out of the scores
"""
import json
from pathlib import Path
import re
import sys
import tempfile

import build_haystack
import graders

SERIAL = re.compile(r"RX-\d{4}")


def perfect(case):
    task = case["task"]
    body = {"canary": case["canary"]}
    if task in {"E-1", "E-3", "E-5"}:
        body["answer"] = case["answer"]
    elif task == "E-2":
        body["answers"] = case["answers"]
    elif task == "E-4":
        body["sum"] = int(case["sum"])
    elif task == "E-6":
        body["answer"] = None
    return json.dumps(body, ensure_ascii=False)


def wrong(case):
    task = case["task"]
    body = {"canary": case["canary"]}
    if task == "E-5":
        body["answer"] = case["decoys"][0]          # took a withdrawn job
    elif task in {"E-1", "E-3"}:
        body["answer"] = "RX-0000"
    elif task == "E-2":
        body["answers"] = case["answers"][:1]       # missed two needles
    elif task == "E-4":
        body["sum"] = int(case["sum"]) + 1
    elif task == "E-6":
        body["answer"] = "RX-1234"                  # invented one
    return json.dumps(body, ensure_ascii=False)


def check_documents(root, key):
    problems = []
    for case in key["cases"]:
        doc = (root / f"{case['id']}.md").read_text(encoding="utf-8")
        if case["canary"] not in doc:
            problems.append(f"{case['id']}: canary missing from document")
        if case["task"] in {"E-1", "E-3", "E-5"}:
            if case["answer"] not in doc:
                problems.append(f"{case['id']}: needle {case['answer']} missing")
            if doc.count(case["answer"]) != 1:
                problems.append(f"{case['id']}: needle appears more than once")
        if case["task"] == "E-2":
            for v in case["answers"]:
                if doc.count(v) != 1:
                    problems.append(f"{case['id']}: needle {v} not unique")
        if case["task"] == "E-6":
            if SERIAL.search(doc):
                problems.append(f"{case['id']}: abstention case contains a serial")
        if case["task"] == "E-4":
            if doc.count("※集計対象") != len(case["answers"]):
                problems.append(f"{case['id']}: aggregation markers miscounted")
    return problems


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "hay"
        key = build_haystack.build(root, [1000, 4000], [0.0, 0.5, 1.0],
                                   build_haystack.TASKS, "selftest", 1.4)
        cases = key["cases"]
        print(f"--- documents ({len(cases)} cases) ---")
        problems = check_documents(root, key)
        for p in problems[:8]:
            print(f"  BAD {p}")
        print("  OK  every needle planted, unique, and absent from abstention cases"
              if not problems else f"  {len(problems)} problem(s)")

        print("--- perfect answers ---")
        bad = [c["id"] for c in cases if not graders.grade(c, perfect(c))["passed"]]
        for cid in bad[:5]:
            print(f"  BAD {cid} should have passed")
        print("  OK  all cases pass" if not bad else f"  {len(bad)} failed")

        print("--- wrong answers ---")
        leaks = []
        for c in cases:
            r = graders.grade(c, wrong(c))
            if r["passed"] or not r["violations"]:
                leaks.append(c["id"])
        decoy = next(c for c in cases if c["task"] == "E-5")
        decoy_r = graders.grade(decoy, wrong(decoy))
        fab = next(c for c in cases if c["task"] == "E-6")
        fab_r = graders.grade(fab, wrong(fab))
        print("  OK  all rejected" if not leaks else f"  BAD {len(leaks)} slipped through")
        print(f"  {'OK ' if decoy_r['metrics'].get('picked_decoy') else 'BAD'} "
              "withdrawn job detected as such")
        print(f"  {'OK ' if fab_r['metrics'].get('fabricated_serial') else 'BAD'} "
              "invented answer detected on the abstention case")

        print("--- lost canary ---")
        c = next(x for x in cases if x["task"] == "E-1")
        body = json.loads(perfect(c))
        body["canary"] = None
        r = graders.grade(c, json.dumps(body, ensure_ascii=False))
        canary_ok = (not r["passed"]) and r["answer_correct"] and not r["canary_ok"]
        print(f"  {'OK ' if canary_ok else 'BAD'} right answer + lost canary "
              "= not passed, reported as truncation")

        ok = (not problems and not bad and not leaks and canary_ok
              and decoy_r["metrics"].get("picked_decoy")
              and fab_r["metrics"].get("fabricated_serial"))
    print()
    print("self-test OK" if ok else "self-test FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

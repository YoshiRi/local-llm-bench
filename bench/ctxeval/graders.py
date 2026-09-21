#!/usr/bin/env python3
"""Graders for the long-context set.

Two independent judgements per case:

  canary_ok   did the very top of the document reach the model? A server that
              silently drops the front of an over-long input can still answer a
              needle placed late in the text. Without this check that looks like
              success, and a failure at the front looks like a model weakness.
  passed      was the task itself answered correctly.

A case with canary_ok false is reported as inconclusive rather than as a model
failure, because the input it saw is not the input that was sent.
"""
import json
import re

SERIAL = re.compile(r"RX-\d{4}")
NULLISH = {"", "null", "none", "なし", "記載なし", "不明", "n/a", "na", "-"}


def load_json(text):
    for candidate in (text, ):
        m = re.search(r"\{.*\}", candidate, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _norm(v):
    return re.sub(r"\s", "", str(v)).upper() if v is not None else None


def _is_null(v):
    return v is None or str(v).strip().lower() in NULLISH


def grade(case, text):
    data = load_json(text)
    base = {"id": case["id"], "task": case["task"],
            "target_tokens": case["target_tokens"], "depth": case["depth"]}
    if data is None:
        return {**base, "passed": False, "canary_ok": False,
                "metrics": {"parsed": False},
                "violations": ["answer is not valid JSON"]}

    got_canary = _norm(data.get("canary"))
    canary_ok = got_canary == _norm(case["canary"])
    metrics = {"parsed": True, "canary_expected": case["canary"],
               "canary_got": data.get("canary"), "canary_ok": canary_ok}
    violations = []
    if not canary_ok:
        violations.append(
            "canary missing or wrong: the front of the document did not reach "
            "the model (input truncation), or it was not read")

    task = case["task"]
    if task in {"E-1", "E-3", "E-5"}:
        got = _norm(data.get("answer"))
        want = _norm(case["answer"])
        ok = got == want
        metrics.update({"answer_got": data.get("answer"), "answer_expected": case["answer"]})
        if task == "E-5" and got in {_norm(d) for d in case.get("decoys", [])}:
            violations.append(f"picked a withdrawn (取消) job: {data.get('answer')}")
            metrics["picked_decoy"] = True
        elif not ok:
            violations.append(f"expected {case['answer']}, got {data.get('answer')}")
        if task == "E-3":
            metrics["pointer"] = case.get("pointer")

    elif task == "E-2":
        got = {_norm(x) for x in (data.get("answers") or []) if x is not None}
        want = {_norm(x) for x in case["answers"]}
        missing = sorted(want - got)
        extra = sorted(got - want)
        ok = not missing and not extra
        metrics.update({"missing": missing, "extra": extra,
                        "recall": round(len(want & got) / len(want), 4)})
        violations += [f"missing {m}" for m in missing] + [f"invented {e}" for e in extra]

    elif task == "E-4":
        got = re.sub(r"[,\s]", "", str(data.get("sum", "")))
        ok = got == case["sum"]
        metrics.update({"sum_got": data.get("sum"), "sum_expected": case["sum"],
                        "terms": case["answers"]})
        if not ok:
            violations.append(f"expected sum {case['sum']}, got {data.get('sum')}")

    elif task == "E-6":
        answer = data.get("answer")
        ok = _is_null(answer)
        metrics.update({"answer_got": answer,
                        "fabricated_serial": bool(SERIAL.search(str(answer or "")))})
        if not ok:
            violations.append(
                f"invented an answer where the document has none: {answer!r}")
    else:
        raise ValueError(task)

    return {**base, "passed": bool(ok and canary_ok), "answer_correct": bool(ok),
            "canary_ok": canary_ok, "metrics": metrics, "violations": violations}

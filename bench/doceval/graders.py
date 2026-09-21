#!/usr/bin/env python3
"""Predicate graders for the document-processing tasks.

Every grader is mechanical: it compares the model output against the planted
answer key, never against a human-written reference. Positive predicates check
that the required work happened; negative predicates check that nothing extra
happened. A task passes only when both hold.

Known limitation: fabrication detection (A-3) covers numerals, Latin-script
tokens and wikilink names only. A fabricated Japanese proper noun is NOT caught.
"""
import json
import re
import unicodedata

FENCE = re.compile(r"```[a-zA-Z0-9_-]*\n(.*?)```", re.S)
NUMERIC = re.compile(r"\d+(?:\.\d+)?")
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]*")
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
BULLET = re.compile(r"^\s*(?:[-*+・]|\d+[.)])\s+", re.M)
TAG = re.compile(r"(?:domain|type|status)/[A-Za-z0-9_\-]+")


def strip_fences(text):
    """Return fenced block contents when present, else the text itself."""
    blocks = FENCE.findall(text)
    return blocks[0] if blocks else text


def load_json(text):
    """Best-effort JSON extraction. Returns None when nothing parses."""
    for candidate in (strip_fences(text), text):
        candidate = candidate.strip()
        for opener, closer in (("[", "]"), ("{", "}")):
            i, j = candidate.find(opener), candidate.rfind(closer)
            if i == -1 or j <= i:
                continue
            try:
                return json.loads(candidate[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None


def norm(s):
    """NFKC fold so full-width digits and Latin letters compare equal."""
    return unicodedata.normalize("NFKC", str(s)).strip()


def _result(task, passed, metrics, violations):
    return {"task": task, "passed": bool(passed), "metrics": metrics,
            "violations": violations}


# --- A-1 extraction ---------------------------------------------------------

def grade_a1(output, key):
    gold = {(norm(d["section"]), norm(d["value"]), norm(d["unit"]))
            for d in key["a1"]["pairs"]}
    data = load_json(output)
    if not isinstance(data, list):
        return _result("A-1", False, {"parsed": False, "recall": 0.0, "precision": 0.0},
                       ["output is not a JSON array"])
    got = set()
    malformed = 0
    for item in data:
        if not isinstance(item, dict) or not {"section", "value", "unit"} <= set(item):
            malformed += 1
            continue
        got.add((norm(item["section"]), norm(item["value"]), norm(item["unit"])))
    missing = sorted(gold - got)
    extra = sorted(got - gold)
    metrics = {"parsed": True, "malformed_entries": malformed,
               "recall": round(len(gold & got) / len(gold), 4),
               "precision": round(len(gold & got) / len(got), 4) if got else 0.0,
               "missing": missing, "extra": extra}
    violations = ([f"missing {m}" for m in missing] + [f"extra {e}" for e in extra]
                  + ([f"{malformed} malformed entries"] if malformed else []))
    return _result("A-1", not violations, metrics, violations)


# --- A-2 redaction ----------------------------------------------------------

def _atoms(item):
    """Sub-strings that also count as a leak (name parts, email local part)."""
    out = []
    if "@" in item:
        out.append(item.split("@", 1)[0])
    elif " " in item:
        out.extend(part for part in item.split(" ") if len(part) >= 2)
    return out


def grade_a2(output, key):
    low = output.lower()
    leaked, partial = [], []
    for item in key["a2"]["pii"]:
        if item.lower() in low:
            leaked.append(item)
            continue
        for atom in _atoms(item):
            if atom.lower() in low:
                partial.append(f"{item} -> {atom}")
                break
    over_masked = [k for k in key["a2"]["keep"] if k.lower() not in low]
    total = len(key["a2"]["pii"])
    hit = total - len(leaked) - len(partial)
    metrics = {"pii_total": total, "leaked": leaked, "partial_leaks": partial,
               "recall": round(hit / total, 4),
               "over_masked": over_masked,
               "keep_total": len(key["a2"]["keep"])}
    violations = ([f"leaked {x}" for x in leaked]
                  + [f"partial leak {x}" for x in partial]
                  + [f"over-masked {x}" for x in over_masked])
    return _result("A-2", not violations, metrics, violations)


# --- A-3 summary fidelity ---------------------------------------------------

def source_tokens(texts):
    numeric, latin, links = set(), set(), set()
    for t in texts:
        numeric |= set(NUMERIC.findall(t))
        latin |= {m.lower() for m in LATIN.findall(t)}
        links |= {norm(m) for m in WIKILINK.findall(t)}
    return numeric, latin, links


def grade_a3(output, key, sources, allow_small_ints=True):
    numeric, latin, links = source_tokens(sources)
    novel_num = sorted({n for n in NUMERIC.findall(output) if n not in numeric
                        and not (allow_small_ints and n.isdigit() and int(n) <= 10)})
    novel_lat = sorted({m.lower() for m in LATIN.findall(output)} - latin)
    novel_link = sorted({norm(m) for m in WIKILINK.findall(output)} - links)
    chars = len(output.strip())
    limit = key["a3"]["max_chars"]
    fabricated = novel_num + novel_lat + novel_link
    metrics = {"chars": chars, "max_chars": limit,
               "fabrication_count": len(fabricated),
               "novel_numeric": novel_num, "novel_latin": novel_lat,
               "novel_wikilink": novel_link,
               "allow_small_ints": allow_small_ints}
    violations = [f"fabricated {f}" for f in fabricated]
    if chars > limit:
        violations.append(f"length {chars} > {limit}")
    return _result("A-3", not violations, metrics, violations)


# --- A-4 contradiction detection --------------------------------------------

def grade_a4(output, key):
    data = load_json(output)
    entries = None
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                entries = v
                break
    elif isinstance(data, list):
        entries = data
    if entries is None:
        return _result("A-4", False, {"parsed": False, "entry_count": 0},
                       ["output is not a JSON array or object containing one"])
    blob = norm(json.dumps(entries, ensure_ascii=False))
    files_hit = [f for f in key["a4"]["files"] if norm(f).rsplit(".md", 1)[0] in blob]
    values_hit = [v for v in key["a4"]["values"] if v in blob]
    keyword_hit = key["a4"]["keyword"] in blob
    metrics = {"parsed": True, "entry_count": len(entries),
               "files_matched": files_hit, "values_matched": values_hit,
               "keyword_matched": keyword_hit,
               "false_positives": max(0, len(entries) - 1)}
    violations = []
    if len(entries) != 1:
        violations.append(f"expected exactly 1 contradiction, got {len(entries)}")
    if len(files_hit) != 2:
        violations.append(f"did not name both files: {files_hit}")
    if len(values_hit) != 2:
        violations.append(f"did not cite both values: {values_hit}")
    if not keyword_hit:
        violations.append(f"did not name the item '{key['a4']['keyword']}'")
    return _result("A-4", not violations, metrics, violations)


# --- A-5 table to CSV -------------------------------------------------------

def _csv_lines(text):
    body = strip_fences(text)
    lines = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(re.sub(r"\s*,\s*", ",", line))
    return lines


def grade_a5(output, key):
    got = _csv_lines(output)
    gold = key["a5"]["csv"]
    metrics = {"expected_lines": len(gold), "got_lines": len(got), "diff": []}
    violations = []
    for i in range(max(len(gold), len(got))):
        g = gold[i] if i < len(gold) else None
        o = got[i] if i < len(got) else None
        if g != o:
            metrics["diff"].append({"line": i + 1, "expected": g, "got": o})
    if metrics["diff"]:
        violations.append(f"{len(metrics['diff'])} line(s) differ")
    return _result("A-5", not violations, metrics, violations)


# --- A-6 tagging ------------------------------------------------------------

def grade_a6(output, key):
    got = set(TAG.findall(output))
    expected = set(key["a6"]["expected"])
    inventory = set(key["a6"]["inventory"])
    invented = sorted(got - inventory)
    metrics = {"got": sorted(got), "expected": sorted(expected),
               "missing": sorted(expected - got), "extra": sorted(got - expected),
               "invented": invented}
    violations = []
    if got != expected:
        violations.append(f"tag set mismatch: {sorted(got)} != {sorted(expected)}")
    if invented:
        violations.append(f"invented tags not in vault inventory: {invented}")
    return _result("A-6", not violations, metrics, violations)


# --- A-7 compound instruction following -------------------------------------

def grade_a7(output, key):
    body = output.strip()
    chars = len(body)
    limit = key["a7"]["max_chars"]
    bullets = len(BULLET.findall(body))
    missing = [t for t in key["a7"]["required"] if t not in body]
    foreign = [t for t in key["a7"]["foreign"] if t in body]
    metrics = {"chars": chars, "max_chars": limit, "bullet_lines": bullets,
               "missing_required": missing, "foreign_tokens": foreign}
    violations = []
    if chars > limit:
        violations.append(f"length {chars} > {limit}")
    if bullets:
        violations.append(f"{bullets} bullet line(s) despite prose-only instruction")
    if missing:
        violations.append(f"required terms altered or dropped: {missing}")
    if foreign:
        violations.append(f"content from other sections leaked: {foreign}")
    return _result("A-7", not violations, metrics, violations)

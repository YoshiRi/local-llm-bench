#!/usr/bin/env python3
"""Generate Japanese long-context documents and their answer keys.

Task taxonomy is borrowed from RULER (single needle, multiple needles,
multi-hop tracing, aggregation, distractors) but every character is generated
here, in Japanese, from a seeded PRNG. Published English haystacks tokenise
differently and say nothing about how Japanese documents behave on this machine.

Two properties make the result gradeable:

  needles   every planted fact is a unique, unambiguous token that cannot occur
            in the filler, so a correct answer cannot be produced by chance.
  canary    a marker sits at the very top of every document. A server that
            silently drops the front of an over-long input still answers the
            needle but loses the canary, which is how truncation is detected
            rather than mistaken for a model failure.

Lengths are requested in approximate tokens and realised as characters; the
real token count is whatever the server reports, and that is what gets recorded.
"""
import argparse
import json
from pathlib import Path
import random

# Japanese filler that reads like a measurement log. Numbers here are decoys:
# none of them are ever the answer, and none carry the aggregation marker.
DATASETS = ["D-1{:02d}".format(i) for i in range(10, 90)]
TOPICS = ["前方カメラ", "後方カメラ", "LiDAR", "レーダー", "統合パイプライン",
          "前処理", "後処理", "同期処理"]
JUDGEMENTS = ["再測定は不要と判断した", "翌週に再測定する", "担当者へ共有済み",
              "条件を変えて追試する", "既知の事象として記録した"]


def filler_sentence(rng):
    return (f"{rng.randint(2025, 2026)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d} の計測では、"
            f"{rng.choice(DATASETS)} の{rng.choice(TOPICS)}について "
            f"処理レートが {rng.randint(10, 30)}.{rng.randint(0, 9)} fps、"
            f"欠損率が 0.{rng.randint(10, 49)} だった。{rng.choice(JUDGEMENTS)}。")


def filler_paragraphs(rng, count):
    return ["".join(filler_sentence(rng) for _ in range(rng.randint(2, 4)))
            for _ in range(count)]


CANARY_LINE = "この資料の管理番号は {canary} である。末尾まで欠落なく読み取ること。"


def make_canary(rng):
    return "CN-{:04d}-{:04d}".format(rng.randint(1000, 9999), rng.randint(1000, 9999))


def make_serial(rng, prefix):
    return "{}-{:04d}".format(prefix, rng.randint(1000, 9999))


def insert(paragraphs, text, depth):
    """Place text at a fractional depth through the paragraph list."""
    i = min(len(paragraphs), max(0, round(depth * len(paragraphs))))
    return paragraphs[:i] + [text] + paragraphs[i:]


def assemble(title, canary, paragraphs):
    head = ["# " + title, CANARY_LINE.format(canary=canary)]
    return "\n\n".join(head + paragraphs) + "\n"


PARAGRAPH_CHARS = 215  # measured average of the generated filler


def approx_paragraph_count(target_tokens, chars_per_token):
    return max(4, round(target_tokens * chars_per_token / PARAGRAPH_CHARS))


def build_case(task, target_tokens, depth, seed, chars_per_token):
    rng = random.Random(f"{task}-{target_tokens}-{depth}-{seed}")
    n = approx_paragraph_count(target_tokens, chars_per_token)
    paras = filler_paragraphs(rng, n)
    canary = make_canary(rng)
    key = {"task": task, "target_tokens": target_tokens, "depth": depth,
           "canary": canary}

    if task == "E-1":                                   # single needle
        v = make_serial(rng, "RX")
        paras = insert(paras, f"解析ジョブ {v} が本件の対象である。", depth)
        key["answer"] = v

    elif task == "E-2":                                 # three needles, spread out
        vals = [make_serial(rng, "RX") for _ in range(3)]
        for k, v in enumerate(vals):
            d = [0.15, 0.5, 0.85][k]
            paras = insert(paras, f"対象の解析ジョブとして {v} が登録されている。", d)
        key["answers"] = vals

    elif task == "E-3":                                 # two hops
        pointer = make_serial(rng, "SEC")
        v = make_serial(rng, "RX")
        paras = insert(paras, f"本件の対象ジョブは、付録 {pointer} に記載のものとする。", depth)
        paras = insert(paras, f"付録 {pointer}: 対象ジョブは {v} である。",
                       min(0.97, depth + 0.4))
        key["answer"] = v
        key["pointer"] = pointer

    elif task == "E-4":                                 # aggregation
        vals = [rng.randint(100, 999) for _ in range(4)]
        for k, v in enumerate(vals):
            paras = insert(paras, f"※集計対象: 検出件数 {v} 件。", 0.1 + 0.2 * k)
        key["answers"] = [str(v) for v in vals]
        key["sum"] = str(sum(vals))

    elif task == "E-5":                                 # one real needle, three decoys
        v = make_serial(rng, "RX")
        decoys = [make_serial(rng, "RX") for _ in range(3)]
        paras = insert(paras, f"【確定】対象の解析ジョブは {v} である。", depth)
        for k, d in enumerate(decoys):
            paras = insert(paras, f"【取消】対象候補だった解析ジョブ {d} は取り下げられた。",
                           0.2 + 0.25 * k)
        key["answer"] = v
        key["decoys"] = decoys

    elif task == "E-6":                                 # nothing to find
        key["answer"] = None

    else:
        raise ValueError(task)

    key["document"] = assemble(f"計測記録集 {target_tokens} tokens 相当", canary, paras)
    key["document_chars"] = len(key["document"])
    return key


TASKS = ["E-1", "E-2", "E-3", "E-4", "E-5", "E-6"]
DEFAULT_LENGTHS = [1000, 4000, 8000, 16000, 24000]
DEFAULT_DEPTHS = [0.0, 0.25, 0.5, 0.75, 1.0]


def build(out: Path, lengths, depths, tasks, seed, chars_per_token) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for task in tasks:
        # depth is meaningless where the needles are placed by the task itself
        case_depths = depths if task in {"E-1", "E-3", "E-5"} else [0.5]
        for tokens in lengths:
            for depth in case_depths:
                c = build_case(task, tokens, depth, seed, chars_per_token)
                cid = f"{task}_{tokens}_{int(depth*100):03d}"
                c["id"] = cid
                (out / f"{cid}.md").write_text(c.pop("document"), encoding="utf-8")
                cases.append(c)
    key = {"generator": "build_haystack.py", "seed": seed,
           "chars_per_token_assumed": chars_per_token,
           "lengths": lengths, "depths": depths, "tasks": tasks,
           "case_count": len(cases), "cases": cases}
    (out / "answer_key.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return key


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--lengths", type=int, nargs="+", default=DEFAULT_LENGTHS)
    p.add_argument("--depths", type=float, nargs="+", default=DEFAULT_DEPTHS)
    p.add_argument("--tasks", nargs="+", default=TASKS, choices=TASKS)
    p.add_argument("--seed", default="ctxeval-1")
    p.add_argument("--chars-per-token", type=float, default=1.4,
                   help="Japanese estimate used only to size the filler")
    a = p.parse_args()
    key = build(a.out, a.lengths, a.depths, a.tasks, a.seed, a.chars_per_token)
    print(f"{key['case_count']} cases at {a.out}")
    for t in a.tasks:
        sizes = [c["document_chars"] for c in key["cases"] if c["task"] == t]
        print(f"  {t}: {len(sizes)} cases, {min(sizes)}-{max(sizes)} chars")


if __name__ == "__main__":
    main()

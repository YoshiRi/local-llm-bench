"""Grade SemIf results against jeveval's answer key. Prints per-task accuracy,
majority-class baseline, latency, and a confusion table for J-1."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, type=Path)
    ap.add_argument("--results", required=True, type=Path)
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()
    key = json.load(open(a.key, encoding="utf-8"))
    rows = [json.loads(l) for l in open(a.results, encoding="utf-8") if l.strip()]
    per = defaultdict(list)
    confusion = defaultdict(Counter)
    for r in rows:
        k = key.get(r["id"])
        if not k:
            continue
        pred = r["option_ids"][max(range(len(r["probabilities"])), key=lambda i: r["probabilities"][i])]
        conf = max(r["probabilities"])
        per[k["task"]].append({"id": r["id"], "gold": k["answer"], "pred": pred, "conf": conf,
                               "ok": pred == k["answer"], "sec": r.get("forward_seconds"),
                               "tokens": r.get("input_tokens")})
        if k["task"] == "J-1":
            confusion[k["answer"]][pred] += 1
    report = {"tasks": {}}
    for task in sorted(per):
        xs = per[task]
        golds = Counter(x["gold"] for x in xs)
        majority = max(golds.values()) / len(xs)
        acc = sum(x["ok"] for x in xs) / len(xs)
        # balanced accuracy
        recalls = []
        for g, n in golds.items():
            recalls.append(sum(x["ok"] for x in xs if x["gold"] == g) / n)
        bal = sum(recalls) / len(recalls)
        secs = [x["sec"] for x in xs if x["sec"] is not None]
        wrong_conf = [x["conf"] for x in xs if not x["ok"]]
        right_conf = [x["conf"] for x in xs if x["ok"]]
        t = {
            "n": len(xs), "accuracy": round(acc, 3), "balanced_accuracy": round(bal, 3),
            "majority_baseline": round(majority, 3),
            "mean_forward_s": round(sum(secs) / len(secs), 3) if secs else None,
            "mean_conf_when_right": round(sum(right_conf) / len(right_conf), 3) if right_conf else None,
            "mean_conf_when_wrong": round(sum(wrong_conf) / len(wrong_conf), 3) if wrong_conf else None,
            "wrong": [{"id": x["id"], "gold": x["gold"], "pred": x["pred"], "conf": round(x["conf"], 3)} for x in xs if not x["ok"]],
        }
        if task == "J-3":
            tp = sum(1 for x in xs if x["gold"] == "yes" and x["pred"] == "yes")
            fp = sum(1 for x in xs if x["gold"] == "no" and x["pred"] == "yes")
            fn = sum(1 for x in xs if x["gold"] == "yes" and x["pred"] == "no")
            t["pii_recall"] = round(tp / (tp + fn), 3) if tp + fn else None
            t["pii_precision"] = round(tp / (tp + fp), 3) if tp + fp else None
        report["tasks"][task] = t
        print(f"{task}: n={t['n']} acc={t['accuracy']} balanced={t['balanced_accuracy']} "
              f"majority={t['majority_baseline']} mean_forward={t['mean_forward_s']}s"
              + (f" pii_recall={t['pii_recall']} pii_precision={t['pii_precision']}" if task == "J-3" else ""))
    if confusion:
        labels = sorted(confusion)
        print("J-1 confusion (rows=gold, cols=pred):")
        print("            " + " ".join(f"{l[:6]:>6}" for l in labels))
        for g in labels:
            print(f"{g[:11]:>11} " + " ".join(f"{confusion[g][p]:>6}" for p in labels))
        report["j1_confusion"] = {g: dict(confusion[g]) for g in labels}
    if a.report:
        json.dump(report, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("report:", a.report)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Offline self-test: prove the graders behave without contacting any model.

Builds the vault in a temporary directory, feeds each grader a deliberately
perfect answer and a deliberately flawed one, and asserts that the perfect set
passes everything while the flawed set trips the intended predicate. Run this
after editing build_vault.py, tasks.py or graders.py.
"""
import json
from pathlib import Path
import sys
import tempfile

import build_vault
import tasks as tasklib

SUMMARY_OK = (
    "2026-08-11 の計測では平均処理レート 18.4 fps、最小 12.7 fps、フレームあたりの遅延 "
    "54.3 ms、常駐メモリ 19.6 GiB、ピーク 23.0 GiB、検出率 91.2 %、誤検出率 3.8 %、"
    "評価フレーム数 4820 枚だった。2026-08-18 の再測定では推論バッチを 2 から 4 へ変更し、"
    "常駐メモリ 21.3 GiB、ピーク 25.8 GiB、平均処理レート 19.1 fps となった。ピークは "
    "GPU割当上限の直下である。2026-08-25 の障害報告では polargrid filter の Diag が連続で "
    "error を報告してパイプラインが停止した。停止までは 47 秒。原因は欠損率のしきい値 0.35 が"
    "実測に合わず、欠損率 0.41 で超過したことで、しきい値を 0.45 へ変更して再現しなくなった。"
)

CAUSE_OK = (
    "polargrid filter の Diag 判定は、入力点群の欠損率をしきい値 0.35 と比較していた。"
    "再測定で欠損率が 0.41 に上がってしきい値を超えたため、error の報告に至った。"
    "Diag の判定自体は仕様どおりであり、問題はしきい値の設定が実測に合っていなかった点にある。"
)


def perfect(vault, key):
    memo = (vault / key["a2"]["file"]).read_text(encoding="utf-8")
    for item in key["a2"]["pii"]:
        memo = memo.replace(item, "███")
    return {
        "A-1": json.dumps(key["a1"]["pairs"], ensure_ascii=False),
        "A-2": memo,
        "A-3": SUMMARY_OK,
        "A-4": json.dumps({"矛盾": [{"file_a": "索引.md",
                                     "file_b": "計測記録 2026-08-18.md",
                                     "項目": "メモリピーク",
                                     "値_a": "23.0 GiB", "値_b": "25.8 GiB"}]},
                          ensure_ascii=False),
        "A-5": "\n".join(key["a5"]["csv"]),
        "A-6": "\n".join(key["a6"]["expected"]),
        "A-7": CAUSE_OK,
    }


def flawed(vault, key):
    memo = (vault / key["a2"]["file"]).read_text(encoding="utf-8")
    for item in key["a2"]["pii"]:
        # leave the family name behind, and destroy a value that must survive
        memo = memo.replace(item, "███" if item != "佐々木 玲奈" else "佐々木 ███")
    memo = memo.replace("25.8", "███")
    pairs = [p for p in key["a1"]["pairs"] if p["value"] != "4820"]
    pairs.append({"section": "メモリ", "value": "26.0", "unit": "GiB"})
    return {
        "A-1": json.dumps(pairs, ensure_ascii=False),
        "A-2": memo,
        "A-3": SUMMARY_OK + "なお推論は TensorRT 上で実行され、平均遅延は 99.9 ms だった。",
        "A-4": json.dumps({"矛盾": [
            {"file_a": "索引.md", "file_b": "計測記録 2026-08-18.md",
             "項目": "メモリピーク", "値_a": "23.0", "値_b": "25.8"},
            {"file_a": "索引.md", "file_b": "計測記録 2026-08-18.md",
             "項目": "記録日", "値_a": "2026-08-26", "値_b": "2026-08-18"}]},
            ensure_ascii=False),
        "A-5": "項目, 値\n処理レート, 18.4fps\nメモリピーク, 23 GiB\n検出率, 91.2 %",
        "A-6": "domain/perception\ntype/reference\nstatus/draft",
        "A-7": ("- polargrid filter のしきい値が 0.35 で不適切だった\n"
                "- 対応としてしきい値を 0.45 へ変更した\n"
                "- 停止までの経過時間は 47 秒だった\n"),
    }


def run(label, outputs, vault, key, expect_pass):
    print(f"--- {label} (expect passed={expect_pass}) ---")
    ok = True
    for t in tasklib.TASKS:
        r = t["grade"](outputs[t["id"]], vault, key)
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  [{mark}] {t['id']} {t['title']}")
        for v in r["violations"][:3]:
            print(f"         - {v}")
        if r["passed"] != expect_pass:
            print(f"         !! unexpected result for {t['id']}")
            ok = False
        if not expect_pass and not r["violations"]:
            print(f"         !! {t['id']} failed without naming a violation")
            ok = False
    return ok


def main():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp) / "vault"
        key = build_vault.build(vault)
        good = run("perfect answers", perfect(vault, key), vault, key, True)
        bad = run("flawed answers", flawed(vault, key), vault, key, False)

        # targeted assertions on the flawed set
        f = flawed(vault, key)
        checks = [
            ("A-2 partial leak detected",
             any("佐々木" in v for v in tasklib.BY_ID["A-2"]["grade"](f["A-2"], vault, key)["violations"])),
            ("A-2 over-masking detected",
             "25.8" in str(tasklib.BY_ID["A-2"]["grade"](f["A-2"], vault, key)["metrics"]["over_masked"])),
            ("A-3 fabrication count == 2",
             tasklib.BY_ID["A-3"]["grade"](f["A-3"], vault, key)["metrics"]["fabrication_count"] == 2),
            ("A-4 false positive counted",
             tasklib.BY_ID["A-4"]["grade"](f["A-4"], vault, key)["metrics"]["false_positives"] == 1),
            ("A-6 invented tag detected",
             tasklib.BY_ID["A-6"]["grade"](f["A-6"], vault, key)["metrics"]["invented"] == ["status/draft"]),
            ("A-7 bullets detected",
             tasklib.BY_ID["A-7"]["grade"](f["A-7"], vault, key)["metrics"]["bullet_lines"] == 3),
            ("A-7 foreign tokens detected",
             set(tasklib.BY_ID["A-7"]["grade"](f["A-7"], vault, key)["metrics"]["foreign_tokens"]) == {"47", "0.45"}),
        ]
        print("--- targeted checks ---")
        for name, passed in checks:
            print(f"  [{'OK ' if passed else 'BAD'}] {name}")
        targeted = all(p for _, p in checks)

    print()
    if good and bad and targeted:
        print("self-test OK")
        return 0
    print("self-test FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())

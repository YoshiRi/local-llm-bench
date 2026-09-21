#!/usr/bin/env python3
"""Generate the synthetic Japanese vault and its answer key.

The vault imitates the structure of the real Obsidian vault (frontmatter tag
triples, wikilinks, aligned tables, section headings, measurement prose) but
contains NO real data. Every planted item -- PII, contradiction, measurement
pair -- is emitted into answer_key.json, so grading needs no human gold set.

Output is deterministic: the same command always produces byte-identical files.
"""
import argparse
import json
from pathlib import Path

NOTES = {}

NOTES["索引.md"] = """---
tags:
  - domain/perception
  - type/index
  - status/active
---

# 検証索引

最終照合: 2026-08-26。各記録の役割と現在の要約値をまとめる。

## 関連ノート

- 計測の一次記録: [[計測記録 2026-08-11]]
- 再測定の記録: [[計測記録 2026-08-18]]
- 打合せの記録: [[打合せメモ 2026-08-20]]
- 障害の記録: [[障害報告 2026-08-25]]
- 運用手順: [[運用手順]]

## 結果の要約

| 項目 | 値 |
| --- | ---: |
| 処理レート | 19.1 fps |
| メモリピーク | 23.0 GiB |
| 検出率 | 91.2 % |

処理レートとメモリピークは [[計測記録 2026-08-18]] の再測定に基づく。検出率は [[計測記録 2026-08-11]] の値を据え置いている。
"""

NOTES["計測記録 2026-08-11.md"] = """---
tags:
  - domain/perception
  - type/reference
  - status/active
---

# 計測記録 2026-08-11

対象は [[運用手順]] のとおり起動した検証環境。単発の測定であり、再現性は別途確認する。

## 処理性能

平均処理レートは 18.4 fps、最小は 12.7 fps だった。フレームあたりの遅延は 54.3 ms。

## メモリ

常駐時のメモリは 19.6 GiB、ピークは 23.0 GiB。スワップは発生していない。

## 検出性能

検出率は 91.2 %、誤検出率は 3.8 %。評価フレーム数は 4820 枚。
"""

NOTES["計測記録 2026-08-18.md"] = """---
tags:
  - domain/perception
  - type/reference
  - status/active
---

# 計測記録 2026-08-18

[[計測記録 2026-08-11]] と同じ条件での再測定。変更点は推論バッチのみ。

## 変更点

推論バッチを 2 から 4 へ変更した。他の設定は据え置き。

## メモリ

常駐時のメモリは 21.3 GiB、ピークは 25.8 GiB。GPU割当上限の直下である。

## 処理性能

平均処理レートは 19.1 fps。遅延の再測定は未実施。
"""

NOTES["打合せメモ 2026-08-20.md"] = """---
tags:
  - domain/perception
  - type/capture
  - status/active
---

# 打合せメモ 2026-08-20

出席: 佐々木 玲奈、日野 孝太郎、Priya Raghavan

## 連絡先

- 佐々木 玲奈: reina.sasaki@example-motors.co.jp
- 日野 孝太郎: kotaro.hino@example-motors.co.jp
- Priya Raghavan: priya.raghavan@example-lab.example

## 検証環境

評価サーバーは 192.168.31.204、予備機は 192.168.31.211。対象車両は X2-GEN2-0147 と X2-GEN2-0203。

## 決定事項

再測定の結果は [[計測記録 2026-08-18]] に記録する。メモリピークが 25.8 GiB のため、割当上限の見直しを検討する。
"""

NOTES["障害報告 2026-08-25.md"] = """---
tags:
  - domain/perception
  - type/issue
  - status/active
---

# 障害報告 2026-08-25

## 事象

評価中に polargrid filter の Diag が連続で error を報告し、パイプラインが停止した。停止までの経過時間は 47 秒。

## 原因

polargrid filter の Diag 判定が、入力点群の欠損率をしきい値 0.35 と比較していた。再測定で欠損率が 0.41 に上がり、しきい値を超えた。Diag の判定自体は仕様どおりで、しきい値の設定が実測に合っていなかった。

## 対応

しきい値を 0.45 へ変更した。変更後の再現試験では停止しなかった。
"""

NOTES["運用手順.md"] = """---
tags:
  - domain/perception
  - type/howto
  - status/active
---

# 運用手順

## 起動

評価サーバーを起動し、[[索引]] の記録先を確認する。起動順は毎回同じにする。

## 停止

処理の完了を確認してから停止する。ログは 14 日間保持する。
"""

NOTES["新規ノート.md"] = """# 再現試験の手順

## 準備

1. 評価サーバーを起動する。
2. [[障害報告 2026-08-25]] で変更したしきい値が反映されているか確認する。

## 実施

1. 同じ入力で再現試験を実行する。
2. 停止が発生しないことを確認する。

## 後片付け

1. ログを保存してからサーバーを停止する。
"""

# --- planted answer key -----------------------------------------------------

# A-1: every "<number> <unit>" pair in 計測記録 2026-08-11.md, by section.
A1_PAIRS = [
    {"section": "処理性能", "value": "18.4", "unit": "fps"},
    {"section": "処理性能", "value": "12.7", "unit": "fps"},
    {"section": "処理性能", "value": "54.3", "unit": "ms"},
    {"section": "メモリ", "value": "19.6", "unit": "GiB"},
    {"section": "メモリ", "value": "23.0", "unit": "GiB"},
    {"section": "検出性能", "value": "91.2", "unit": "%"},
    {"section": "検出性能", "value": "3.8", "unit": "%"},
    {"section": "検出性能", "value": "4820", "unit": "枚"},
]

# A-2: every string that must disappear, and every string that must survive.
A2_PII = [
    "佐々木 玲奈", "日野 孝太郎", "Priya Raghavan",
    "reina.sasaki@example-motors.co.jp",
    "kotaro.hino@example-motors.co.jp",
    "priya.raghavan@example-lab.example",
    "192.168.31.204", "192.168.31.211",
    "X2-GEN2-0147", "X2-GEN2-0203",
]
A2_KEEP = ["25.8", "GiB", "計測記録 2026-08-18", "メモリピーク", "割当上限"]

# A-3: fidelity is graded against the union of these files.
A3_SOURCES = ["計測記録 2026-08-11.md", "計測記録 2026-08-18.md", "障害報告 2026-08-25.md"]
A3_MAX_CHARS = 800

# A-4: exactly one contradiction is planted.
A4_TRUTH = {
    "files": ["索引.md", "計測記録 2026-08-18.md"],
    "values": ["23.0", "25.8"],
    "keyword": "メモリピーク",
}

# A-5: the 索引.md summary table as CSV.
A5_CSV = ["項目,値", "処理レート,19.1 fps", "メモリピーク,23.0 GiB", "検出率,91.2 %"]

# A-6: tag inventory actually used by the vault, and the expected answer.
A6_INVENTORY = ["domain/perception", "type/index", "type/reference", "type/capture",
                "type/issue", "type/howto", "status/active"]
A6_EXPECTED = ["domain/perception", "type/howto", "status/active"]

# A-7: 原因 section only; these tokens belong to other sections and must not leak.
A7_MAX_CHARS = 400
A7_REQUIRED = ["polargrid", "Diag"]
A7_FOREIGN = ["47", "0.45"]


def build(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    for name, body in NOTES.items():
        (out / name).write_text(body, encoding="utf-8")
    key = {
        "generator": "build_vault.py",
        "seed_version": 2,
        "note_count": len(NOTES),
        "notes": sorted(NOTES),
        "a1": {"file": "計測記録 2026-08-11.md", "pairs": A1_PAIRS},
        "a2": {"file": "打合せメモ 2026-08-20.md", "pii": A2_PII, "keep": A2_KEEP},
        "a3": {"sources": A3_SOURCES, "max_chars": A3_MAX_CHARS},
        "a4": A4_TRUTH,
        "a5": {"file": "索引.md", "csv": A5_CSV},
        "a6": {"file": "新規ノート.md", "inventory": A6_INVENTORY, "expected": A6_EXPECTED},
        "a7": {"file": "障害報告 2026-08-25.md", "section": "原因",
               "max_chars": A7_MAX_CHARS, "required": A7_REQUIRED, "foreign": A7_FOREIGN},
    }
    (out / "answer_key.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return key


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, required=True, help="destination directory")
    a = p.parse_args()
    key = build(a.out)
    print(f"wrote {key['note_count']} notes + answer_key.json to {a.out}")


if __name__ == "__main__":
    main()

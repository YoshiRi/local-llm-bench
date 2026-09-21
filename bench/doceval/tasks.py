#!/usr/bin/env python3
"""Task definitions for the document-processing set (A-1 .. A-7).

All prompts are Japanese and self-contained: the relevant notes are inlined, so
no file tools are involved and L0-L3 (tool protocol, shell, git) cannot affect
the score. This is what separates set A from sets B and C.
"""
import graders


def _note(vault, name):
    return (vault / name).read_text(encoding="utf-8").rstrip()


def _wrap(name, body):
    return f"--- ここから {name} ---\n{body}\n--- ここまで {name} ---"


def a1(vault, key):
    f = key["a1"]["file"]
    return f"""次のノートから、数値と単位の組をすべて抽出してください。

抽出の定義: 本文中で「数値」と「単位」が半角スペース1個で区切られて隣接している箇所。見出しやfrontmatter、日付（2026-08-11 のようなハイフン区切り）は対象外です。

出力形式: JSON配列のみを出力してください。説明文やコードフェンスは不要です。各要素は次の3キーを持ちます。
  "section": その組が現れる節の見出し（"## " を除いた文字列）
  "value": 数値の文字列
  "unit": 単位の文字列

{_wrap(f, _note(vault, f))}"""


def a2(vault, key):
    f = key["a2"]["file"]
    return f"""次のノートを、社外に出せる形に匿名化してください。

秘匿の対象: 人名、メールアドレス、IPアドレス、車両ID。
置換方法: 対象の文字列を ███ に置き換えてください。姓だけ・名だけ・メールの@より前だけを残すことも禁止です。

秘匿対象以外は一切変更しないでください。見出し、frontmatter、測定値、`[[リンク]]`、技術用語はそのまま残します。

出力形式: 匿名化後のノート全文のみを出力してください。説明は不要です。

{_wrap(f, _note(vault, f))}"""


def a3(vault, key):
    notes = "\n\n".join(_wrap(n, _note(vault, n)) for n in key["a3"]["sources"])
    return f"""次の3つのノートを、日本語 {key['a3']['max_chars']} 字以内で要約してください。

厳守事項: 元の3ノートに現れない数値、英字表記、ノート名を書かないでください。推測して補うことも、概算に丸めることも禁止です。書けることが少なくなっても構いません。

出力形式: 要約本文のみを出力してください。

{notes}"""


def a4(vault, key):
    notes = "\n\n".join(_wrap(n, _note(vault, n)) for n in key["a4"]["files"])
    return f"""次の2つのノートを突き合わせ、事実として矛盾している箇所を報告してください。

実際に矛盾している箇所だけを挙げてください。表現の違い、記録日の違い、片方にしか書かれていない項目は矛盾ではありません。

出力形式: JSONのみを出力してください。説明文やコードフェンスは不要です。
{{"矛盾": [{{"file_a": "ファイル名", "file_b": "ファイル名", "項目": "矛盾している項目名", "値_a": "値", "値_b": "値"}}]}}

矛盾が無い場合は空配列にしてください。

{notes}"""


def a5(vault, key):
    f = key["a5"]["file"]
    return f"""次のノートに含まれる「結果の要約」の表をCSVに変換してください。

規則: ヘッダ行を含めます。区切りはカンマ1個で、カンマの前後に空白を入れません。セルの文字列はそのまま使い、単位を分離したり数値を丸めたりしないでください。整列記号の行（| --- |）は出力しません。

出力形式: CSVのみを出力してください。説明やコードフェンスは不要です。

{_wrap(f, _note(vault, f))}"""


def _existing_tags(vault, key):
    """Show how the vault already classifies its notes. Without this the task
    asks the model to follow a convention it was never shown."""
    rows = []
    for name in sorted(key["notes"]):
        if name == key["a6"]["file"]:
            continue
        body = _note(vault, name)
        tags = [ln.strip("- ").strip() for ln in body.splitlines()
                if ln.startswith("  - ")]
        if tags:
            rows.append(f"  {name}: {', '.join(tags)}")
    return "\n".join(rows)


def a6(vault, key):
    f = key["a6"]["file"]
    inv = "\n".join(f"  - {t}" for t in key["a6"]["inventory"])
    return f"""次のノートに、frontmatter用のタグを付けてください。

このvaultで既に使われているタグは以下がすべてです。
{inv}

同じvaultの既存ノートは、次のように分類されています。
{_existing_tags(vault, key)}

規則: 上の一覧にあるタグだけを使い、新しいタグを作らないでください。`domain/`、`type/`、`status/` から1つずつ、合計3個を選びます。**既存ノートの分類の仕方に合わせてください。**

出力形式: 選んだタグを1行に1つ、3行だけ出力してください。説明は不要です。

{_wrap(f, _note(vault, f))}"""


def a7(vault, key):
    f = key["a7"]["file"]
    k = key["a7"]
    return f"""次のノートの「{k['section']}」節**だけ**を要約してください。他の節の内容は含めないでください。

条件:
  - 日本語 {k['max_chars']} 字以内
  - 箇条書きを使わず、地の文で書く
  - {'、'.join(f'`{t}`' for t in k['required'])} という語はそのままの表記で残す

出力形式: 要約本文のみを出力してください。

{_wrap(f, _note(vault, f))}"""


TASKS = [
    {"id": "A-1", "title": "抽出", "layer": "D0", "prompt": a1,
     "grade": lambda out, vault, key: graders.grade_a1(out, key)},
    {"id": "A-2", "title": "匿名化", "layer": "D2", "prompt": a2,
     "grade": lambda out, vault, key: graders.grade_a2(out, key)},
    {"id": "A-3", "title": "要約の忠実性", "layer": "D1", "prompt": a3,
     "grade": lambda out, vault, key: graders.grade_a3(
         out, key, [_note(vault, n) for n in key["a3"]["sources"]])},
    {"id": "A-4", "title": "矛盾検出", "layer": "D4", "prompt": a4,
     "grade": lambda out, vault, key: graders.grade_a4(out, key)},
    {"id": "A-5", "title": "表の構造化", "layer": "D0", "prompt": a5,
     "grade": lambda out, vault, key: graders.grade_a5(out, key)},
    {"id": "A-6", "title": "分類・タグ付け", "layer": "D4", "prompt": a6,
     "grade": lambda out, vault, key: graders.grade_a6(out, key)},
    {"id": "A-7", "title": "複合指示追従", "layer": "D3", "prompt": a7,
     "grade": lambda out, vault, key: graders.grade_a7(out, key)},
]

BY_ID = {t["id"]: t for t in TASKS}

#!/usr/bin/env python3
"""Prompt construction for the long-context set (E-1..E-6).

The instruction comes first, the document in the middle, the question again at
the end. Every task also asks for the canary printed at the very top of the
document, so an answer produced from a silently front-truncated input can be
told apart from one produced from the whole thing.
"""

HEADER = """次の資料を読んで、最後の質問に答えてください。

出力はJSONのみ。説明文やコードフェンスは不要です。
資料の冒頭にある管理番号（`CN-` で始まる）も必ず一緒に答えてください。冒頭が読み取れない場合は `"canary": null` としてください。

{schema}
"""

QUESTIONS = {
    "E-1": ("この資料で対象とされている解析ジョブの番号（`RX-` で始まる）は何ですか。",
            '{"canary": "CN-....", "answer": "RX-...."}'),
    "E-2": ("この資料で対象として登録されている解析ジョブの番号を、**すべて**挙げてください。",
            '{"canary": "CN-....", "answers": ["RX-....", "..."]}'),
    "E-3": ("この資料で対象とされている解析ジョブの番号は何ですか。"
            "本文から付録を参照する必要があります。",
            '{"canary": "CN-....", "answer": "RX-...."}'),
    "E-4": ("「※集計対象」と記された検出件数を**すべて合計**した値はいくつですか。"
            "集計対象の印が無い数値は含めないでください。",
            '{"canary": "CN-....", "sum": 1234}'),
    "E-5": ("【確定】とされている解析ジョブの番号は何ですか。"
            "【取消】とされたものは対象外です。",
            '{"canary": "CN-....", "answer": "RX-...."}'),
    "E-6": ("この資料で対象とされている解析ジョブの番号は何ですか。"
            "**資料に記載が無い場合は推測せず `\"answer\": null` と答えてください。**",
            '{"canary": "CN-....", "answer": null}'),
}


def prompt(case, document):
    question, schema = QUESTIONS[case["task"]]
    return (HEADER.format(schema=f"回答形式:\n{schema}")
            + f"\n質問: {question}\n\n"
            + "--- 資料ここから ---\n" + document + "--- 資料ここまで ---\n\n"
            + f"質問（再掲）: {question}\n")

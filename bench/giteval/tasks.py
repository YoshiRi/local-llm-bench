#!/usr/bin/env python3
"""Git task definitions (B-7..B-9).

The deliverable is the repository's end state, not a written answer -- except
B-7, which also asks for the commit it identified. Each prompt states the
history constraint explicitly: without it, "revert" and "reset" are genuinely
ambiguous, and the task would measure guesswork rather than execution.
"""
import graders

HISTORY_RULE = ("既存の履歴を書き換えないでください。`git reset --hard`、`git rebase`、"
                "force系の操作は使わないこと。過去のcommitはすべて残したまま、"
                "新しいcommitを積んで解決してください。")


def b7(root, key, answers):
    k = key["b7"]
    return f"""作業対象: {root / k['repo']}

このリポジトリでは現在テストが失敗します。確認コマンドは `{k['test_command']}` です。

課題:
1. テストを壊した原因のcommitを特定してください。
2. そのcommitの変更だけを打ち消して、テストが通る状態にしてください。他のcommitの変更は残します。
3. 変更はcommitまで済ませ、作業ツリーをクリーンな状態にしてください。

{HISTORY_RULE}

特定したcommitのハッシュを {answers}/B-7.json に書いてください。
回答形式: {{"bad_commit": "<commit hash>"}}
"""


def b8(root, key, answers):
    k = key["b8"]
    return f"""作業対象: {root / k['repo']}

このリポジトリには `{k['secret_file']}` がcommitされてしまっています。中身は認証情報です。

課題:
1. `{k['secret_file']}` をgitの追跡対象から外してください。
2. **ファイル自体はディスク上に残し、中身も変更しないでください。** ローカルの実行に必要です。
3. 今後同じことが起きないよう、無視設定を追加してください。
4. 変更はcommitまで済ませ、作業ツリーをクリーンな状態にしてください。

{HISTORY_RULE}
過去のcommitに含まれている内容を履歴から消す作業は、今回は不要です。

回答ファイルは不要です。リポジトリの状態が成果物です。
"""


def b9(root, key, answers):
    k = key["b9"]
    return f"""作業対象: {root / k['repo']}

`main` ブランチと `{k['branch']}` ブランチが、どちらも `{k['file']}` を変更しています。

課題:
1. `main` 上で `{k['branch']}` をマージしてください。
2. **両方のブランチの設定を両方とも残してください。** どちらか一方を捨てる解決は不可です。
3. コンフリクトマーカーを残さず、作業ツリーをクリーンな状態にしてください。

{HISTORY_RULE}

回答ファイルは不要です。リポジトリの状態が成果物です。
"""


TASKS = [
    {"id": "B-7", "title": "壊したcommitの特定とrevert", "layer": "L2/L3", "prompt": b7,
     "grade": graders.grade_b7},
    {"id": "B-8", "title": "誤commitの追跡除外", "layer": "L1/L3", "prompt": b8,
     "grade": graders.grade_b8},
    {"id": "B-9", "title": "コンフリクト解決", "layer": "L2/L3", "prompt": b9,
     "grade": graders.grade_b9},
]

BY_ID = {t["id"]: t for t in TASKS}

#!/usr/bin/env python3
"""Investigation tasks (set B). Every task is read-only and shell-driven.

B-1..B-3 search a synthetic file tree with ordinary commands.
B-4..B-6 inspect system state through the sandbox's stub commands, which must
be reachable by bare name via PATH. An absolute path such as /usr/sbin/lsof
bypasses the stub and invalidates the trial; graders flag that separately.

Answers are JSON files written OUTSIDE the sandbox so the tree stays untouched.
"""
import graders

COMMON = """作業環境の説明:
- 調査対象は {root} 以下です。ここは読み取り専用です。**サンドボックス配下のファイルを作成・変更・削除しないでください。**
- 回答は {answers}/{task}.json に書いてください。このディレクトリは書き込み可能です。
- シェルコマンドを使って調べてください。`sysctl`、`lsof`、`netstat`、`ifconfig`、`diskutil`、`df` はこの環境向けに用意されたものがPATHに入っています。**絶対パス（/usr/sbin/lsof など）では呼ばないでください。**
- パスは {root} からの相対パス（`home/...`）で答えてください。
"""


def _head(key, task, answers):
    return COMMON.format(root=key["root"], answers=answers, task=task)


def b1(key, answers):
    return _head(key, "B-1", answers) + """
課題: 設定ファイルを1つ探しています。

覚えていること:
- 中身に `wired_limit` という語が含まれていた
- 設定ファイルらしい形式だった
- 置き場所もファイル名も思い出せない

該当するファイルのパスを特定してください。

回答形式 (B-1.json):
{"path": "home/..."}
"""


def b2(key, answers):
    return _head(key, "B-2", answers) + """
課題: 容量を食っているファイルを調べます。

調査対象の中で、サイズが大きいファイル上位3つを、大きい順に特定してください。サイズはバイト数で答えてください（人間向けの 1.2M のような表記ではなく、整数のバイト数）。

回答形式 (B-2.json):
{"files": [{"path": "home/...", "bytes": 123456}, ... 3件 ...]}
"""


def b3(key, answers):
    return _head(key, "B-3", answers) + """
課題: 内容が完全に同一のファイルの組を、すべて洗い出してください。

ファイル名やサイズが同じでも、中身が1バイトでも違えば別物として扱ってください。同一内容のファイルが3つ以上ある場合は、それらを1つの組にまとめてください。同一の組が存在しないファイルは報告しないでください。

回答形式 (B-3.json):
{"groups": [["home/...", "home/..."], ["home/...", "home/...", "home/..."]]}
"""


def b4(key, answers):
    return _head(key, "B-4", answers) + """
課題: このマシンのメモリまわりの設定を確認してください。

- GPUに割り当て可能なメモリの上限 (`iogpu.wired_limit_mb`) は何MBか
- 物理メモリの総量は何バイトか

回答形式 (B-4.json):
{"wired_limit_mb": 12345, "memsize_bytes": 12345678901}
"""


def b5(key, answers):
    return _head(key, "B-5", answers) + """
課題: このマシンで待ち受けているサーバーの公開範囲を確認してください。

Ollama が待ち受けているアドレスとポートを特定し、それが**LAN上の他のマシンから到達できる状態か**（ループバックのみに閉じていないか）を判定してください。

回答形式 (B-5.json):
{"address": "...", "port": 11434, "lan_exposed": true}
"""


def b6(key, answers):
    return _head(key, "B-6", answers) + """
課題: 外付けSSD (ExtremeSSD) の状態を確認してください。

- 現在マウントされているか
- マウントポイントはどこか
- 空き容量はいくつか（`df` の表示どおりの文字列で構いません）

回答形式 (B-6.json):
{"mounted": true, "mount": "/Volumes/...", "free": "640Gi"}
"""


TASKS = [
    {"id": "B-1", "title": "ヒントからファイル特定", "layer": "L1/L2", "prompt": b1,
     "grade": lambda text, key: graders.grade_b1(text, key)},
    {"id": "B-2", "title": "サイズ上位ファイル", "layer": "L1", "prompt": b2,
     "grade": lambda text, key: graders.grade_b2(text, key)},
    {"id": "B-3", "title": "重複ファイル検出", "layer": "L2", "prompt": b3,
     "grade": lambda text, key: graders.grade_b3(text, key)},
    {"id": "B-4", "title": "メモリ・GPU割当上限", "layer": "L1", "prompt": b4,
     "grade": lambda text, key: graders.grade_b4(text, key)},
    {"id": "B-5", "title": "待ち受けと公開範囲", "layer": "L2", "prompt": b5,
     "grade": lambda text, key: graders.grade_b5(text, key)},
    {"id": "B-6", "title": "外付けディスクの状態", "layer": "L1", "prompt": b6,
     "grade": lambda text, key: graders.grade_b6(text, key)},
]

BY_ID = {t["id"]: t for t in TASKS}

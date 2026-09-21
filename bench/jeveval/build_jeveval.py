"""Build typed-decision (Jev-style) benchmark cases for SemIf.

Three tasks, each with a machine-checkable answer key:
  J-1 tag      : which domain/* tag does a vault note carry (real notes, label = frontmatter)
  J-2 quality  : which of two sentences is the natural Japanese one (clean vs corrupted)
  J-3 pii      : does this line contain personal information (doceval synthetic vault, planted PII)

Writes decisions.jsonl (SemIf input format) and answer_key.json into --out.
Vault text goes only into --out; never commit that directory.
"""
import argparse
import json
import random
import re
from pathlib import Path

DOMAINS = ["perception", "data", "evaluation", "devops", "ai", "hw", "release"]
DOMAIN_DESC = {
    "perception": "自動運転の認識（物体検出・トラッキング・センサ融合・認識パイプライン）に関するノート",
    "data": "データセット・アノテーション・データ収集・rosbag・データ管理に関するノート",
    "evaluation": "評価基盤・評価シナリオ・ベンチマーク・テスト結果の分析に関するノート",
    "devops": "CI/CD・ビルド・Docker・インフラ・開発環境の運用に関するノート",
    "ai": "LLM・AIツール・エージェント・機械学習の活用や検証に関するノート",
    "hw": "ハードウェア・センサ機器・ECU・計算機のスペックや調達に関するノート",
    "release": "リリース計画・バージョン管理・リリース作業・目標値に関するノート",
}


def frontmatter_and_body(text):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    return (m.group(1), m.group(2)) if m else ("", text)


def note_domains(fm):
    return re.findall(r"domain/([a-z0-9_-]+)", fm)


def prose_lines(body):
    out = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith(("#", "|", "-", "*", "```", "[[", "!", ">")):
            continue
        if re.search(r"[。．]$", s) and 20 <= len(s) <= 90 and not re.search(r"https?://|`", s):
            out.append(s)
    return out


def corrupt(s, rng):
    kind = rng.choice(["swap", "drop_particles", "dup", "shuffle_clause"])
    chars = list(s)
    if kind == "swap":
        for _ in range(3):
            i = rng.randrange(0, len(chars) - 2)
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        return "".join(chars)
    if kind == "drop_particles":
        t = re.sub(r"[はがをにでとのへも]", "", s)
        return t if t != s else "".join(chars[::-1])
    if kind == "dup":
        i = rng.randrange(0, len(s) // 2)
        j = i + rng.randrange(4, 10)
        return s[:j] + s[i:j] + s[j:]
    parts = re.split(r"(、)", s)
    if len(parts) >= 3:
        rng.shuffle(parts)
        return "".join(parts)
    return "".join(chars[::-1])


def build_tag(vault, rng, per_class):
    cases, key = [], {}
    by = {d: [] for d in DOMAINS}
    for p in vault.rglob("*.md"):
        if any(x in p.parts for x in ("attachments", "Excalidraw", ".obsidian", "作業ログ")):
            continue
        try:
            fm, body = frontmatter_and_body(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        ds = [d for d in note_domains(fm) if d in DOMAINS]
        if len(ds) != 1:
            continue
        text = re.sub(r"\s+", " ", body).strip()
        if len(text) < 200:
            continue
        by[ds[0]].append((p.name, text[:1200]))
    for d in DOMAINS:
        rng.shuffle(by[d])
        for name, text in by[d][:per_class]:
            cid = f"J-1_{len(cases):03d}"
            cases.append({
                "id": cid,
                "state": f"ノート名: {name}\n\n本文（冒頭）:\n{text}",
                "question": "このノートの主題として最も適切な domain タグはどれか。",
                "options": [{"id": k, "description": DOMAIN_DESC[k]} for k in DOMAINS],
            })
            key[cid] = {"task": "J-1", "answer": d, "note": name}
    return cases, key


def build_quality(vault, rng, n):
    pool = []
    for p in vault.rglob("*.md"):
        if any(x in p.parts for x in ("attachments", "Excalidraw", ".obsidian")):
            continue
        try:
            _, body = frontmatter_and_body(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        pool.extend(prose_lines(body))
    pool = sorted(set(pool))
    rng.shuffle(pool)
    cases, key = [], {}
    for s in pool[:n]:
        bad = corrupt(s, rng)
        if bad == s:
            continue
        cid = f"J-2_{len(cases):03d}"
        a_is_clean = rng.random() < 0.5
        a, b = (s, bad) if a_is_clean else (bad, s)
        cases.append({
            "id": cid,
            "state": f"文A: {a}\n文B: {b}",
            "question": "文Aと文Bのうち、自然で正しい日本語として書かれているのはどちらか。",
            "options": [{"id": "A", "description": "文Aの方が自然で正しい。"},
                        {"id": "B", "description": "文Bの方が自然で正しい。"}],
        })
        key[cid] = {"task": "J-2", "answer": "A" if a_is_clean else "B"}
    return cases, key


def build_pii(doceval_vault, rng):
    k = json.load(open(doceval_vault / "answer_key.json", encoding="utf-8"))
    pii = set(k["a2"]["pii"])
    cases, key = [], {}
    lines = []
    for p in sorted(doceval_vault.glob("*.md")):
        for ln in p.read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if len(s) < 12 or s.startswith(("---", "tags:", "  - ")):
                continue
            lines.append((p.name, s, any(x in s for x in pii)))
    pos = [x for x in lines if x[2]]
    neg = [x for x in lines if not x[2]]
    rng.shuffle(neg)
    for name, s, has in pos + neg[: max(len(pos) * 3, 30)]:
        cid = f"J-3_{len(cases):03d}"
        cases.append({
            "id": cid,
            "state": f"ファイル: {name}\n行: {s}",
            "question": "この行に個人情報（氏名・メールアドレス・IPアドレス・車両や個人を特定できる識別子）が含まれているか。",
            "options": [{"id": "yes", "description": "個人情報が含まれている。"},
                        {"id": "no", "description": "個人情報は含まれていない。"}],
        })
        key[cid] = {"task": "J-3", "answer": "yes" if has else "no"}
    return cases, key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--doceval-vault", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--per-class", type=int, default=12)
    ap.add_argument("--quality-n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20260922)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    cases, key = [], {}
    for c, k in (build_tag(a.vault, rng, a.per_class),
                 build_quality(a.vault, rng, a.quality_n),
                 build_pii(a.doceval_vault, rng)):
        cases += c
        key.update(k)
    with open(a.out / "decisions.jsonl", "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    json.dump(key, open(a.out / "answer_key.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print("cases:", Counter(v["task"] for v in key.values()))


if __name__ == "__main__":
    main()

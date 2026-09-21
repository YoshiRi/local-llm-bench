# Typed-decision evaluation (task set J, Jev-style classifier)

Measures whether a small **decision-only** model — one that returns a
probability per allowed option and never generates text (the "System One"
pattern popularised by TypeSafe's Jev) — is good enough to sit in front of
the big agent models as a router / guardrail / scorer. Backend under test:
[SemIf](https://github.com/TheoLeeCJ/SemIf) (MLX, Qwen3.5-4B, 4-bit), installed
in `../../semif/.venv`.

**Run once, 2026-09-22, Qwen3.5-4B 4-bit on the M4 Mac mini 32GB:**

| task | n | accuracy | balanced | majority baseline | mean input tokens | mean forward |
|---|---:|---:|---:|---:|---:|---:|
| J-1 domain tag (7-way, real vault notes) | 77 | 0.636 | 0.598 | 0.156 | 717 | 2.02 s |
| J-2 which sentence is natural Japanese | 59 | 0.966 | 0.966 | 0.542 | 174 | 0.55 s |
| J-3 does this line contain PII | 35 | **1.000** | 1.000 | 0.857 | 156 | 0.50 s |

J-3 recall 1.0 / precision 1.0. Total 171 decisions in 212 s including model
load. Mean confidence 0.83 when right vs 0.70 when wrong on J-1, so a
confidence threshold can route the uncertain third of cases to a larger model.

## Tasks

| id | what | answer key comes from |
|---|---|---|
| J-1 | pick the `domain/*` tag for a vault note from its first 1200 chars | the note's own frontmatter (real, private data; only notes with exactly one domain tag among 7 classes) |
| J-2 | which of two sentences is the natural one | one sentence is a real vault sentence, the other is the same sentence corrupted (adjacent-char swaps, particle deletion, chunk duplication, clause shuffle); A/B order randomised |
| J-3 | does this line contain personal information | doceval's synthetic vault, whose `answer_key.json` lists every planted PII string; a line is positive if it contains one |

J-1 is deliberately hard: the classes overlap (this is one team's vault where
perception, data and evaluation notes all discuss the same pipeline) and the
labels are human tags, not gold. The biggest confusion, `hw` → `devops`, is on
notes such as `Docker諸々.md` that the vault tags `domain/hw` — the model's
answer is arguably the better label. Read J-1 as "agreement with a noisy
tagger", not as ceiling accuracy.

## Running it

```sh
# build (vault text goes only into --out; do not commit that directory)
python3 build_jeveval.py --vault ~/Documents/obsidean_note \
  --doceval-vault /private/tmp/doceval-vault --out /private/tmp/jeveval

# score with SemIf on MLX
../../semif/.venv/bin/semif-score --backend mlx --mode direct \
  --model Qwen/Qwen3.5-4B --revision 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a --mlx-bits 4 \
  --input /private/tmp/jeveval/decisions.jsonl --output /private/tmp/jeveval/results.jsonl

python3 grade_jeveval.py --key /private/tmp/jeveval/answer_key.json \
  --results /private/tmp/jeveval/results.jsonl --report /private/tmp/jeveval/report.json
```

`--doceval-vault` is any directory produced by `../doceval/run_doceval.py --build-vault`.
Memory: ~2.5 GB for the 4-bit model — this coexists with an Ollama/MTPLX model
only in the ≤2 GB headroom sense discussed in the vault; run it while the big
model is idle. The Qwen3.5-4B download is ~9 GB (bf16) into the HF cache on the
internal disk; quantisation happens at load.

## Known limitations

- One trial per case; J-1/J-2 depend on the vault snapshot and the seed.
- SemIf is a CLI over JSONL with no server mode, and model load costs ~10-20 s
  per invocation. Using it *inside* an agent loop (dsh/Claude Code calling it
  as a tool) needs a persistent process — open-jev exposes a System
  One-compatible HTTP endpoint and is the obvious next thing to try for that.
- Probabilities are uncalibrated (SemIf's author says so); the right/wrong
  confidence gap above is an observation, not a guarantee.

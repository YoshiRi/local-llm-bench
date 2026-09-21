# Document-processing evaluation (task set A)

Measures what a local model is actually going to be used for: processing
confidential documents that cannot leave the machine. Coding ability does not
transfer -- see `ローカルLLM 次の評価セット設計` in the vault for the evidence.

**Run against 6 configurations as of 2026-09-21** (Qwen3.6 GGUF/MLX, Ornith,
Gemma4, Coder DWQ v2, Qwen3.6 mxfp4) via `--run`. See `../INVOCATIONS.md` for
the exact commands and each runtime's sampling-parameter caveats.

## The seed is synthetic, on purpose

`build_vault.py` generates seven Japanese notes that imitate the real vault's
structure (frontmatter tag triples, wikilinks, aligned tables, section
headings, measurement prose) and contain **no real data**. Never point this
harness at the real vault: tasks A-2 and A-3 deliberately concern PII, and the
whole point of a synthetic seed is that every planted item -- each PII string,
the single contradiction, every measurement pair -- is written to
`answer_key.json`, so grading needs no human gold set and stays exact.

Output is deterministic; the same command produces byte-identical files.
`answer_key.json` carries a `seed_version`; reports record which seed they were
graded against, because a key fix makes older runs incomparable.

**seed_version 2 (2026-09-20)** repaired two defective gold answers found on the
first real run. A-4 contained a second, unintended contradiction (処理レート
18.4 vs 19.1 fps), so models that correctly reported both were marked wrong; the
index now agrees with the re-measurement. A-6 asked the model to follow the
vault's tagging convention without showing it that convention, so every
configuration gave the same answer and all of them were scored as failures; the
prompt now lists how the other notes are tagged, and the target note is an
unambiguous procedure. Results graded against seed_version 1 for A-4, A-5 and
A-6 are not comparable with later runs.

## Tasks

| id | title | layer | what fails it |
|---|---|---|---|
| A-1 | 抽出 | D0 | any missing or extra (section, value, unit) triple |
| A-2 | 匿名化 | D2 | one leaked PII string, a surviving name part, or over-masking |
| A-3 | 要約の忠実性 | D1 | one fabricated numeral / Latin token / wikilink, or length |
| A-4 | 矛盾検出 | D4 | missing the planted contradiction, or reporting extra ones |
| A-5 | 表の構造化 | D0 | any CSV line differing after whitespace normalization |
| A-6 | 分類・タグ付け | D4 | wrong tag set, or a tag outside the vault inventory |
| A-7 | 複合指示追従 | D3 | length, bullets, altered required terms, other-section leakage |

Layers are D0 抽出 / D1 忠実性 / D2 網羅 / D3 指示追従 / D4 判断.

Prompts are Japanese and self-contained: the notes are inlined in the prompt,
so no file tools are involved and tool-protocol/shell/git ability cannot affect
the score. That separation is the reason set A exists apart from sets B and C.

Grading is by predicate, never by comparison with a reference text. Positive
predicates check the work happened; negative predicates check nothing extra
happened. A task passes only when both hold. For confidential-document work the
negative predicates matter more: A-2 requires recall 1.0 (one leak fails the
task) and A-3 treats fabrication, not prose quality, as the defect.

## Three modes, independently usable

Run the prompts elsewhere and grade here:

```sh
python3 run_doceval.py --build-vault /private/tmp/doceval-vault \
                       --emit /private/tmp/doceval-run
# send each *.prompt.txt as a single user message at temperature 0,
# save replies verbatim as A-1.txt ... A-7.txt (see HOWTO.txt)
python3 run_doceval.py --vault /private/tmp/doceval-vault \
                       --grade /private/tmp/doceval-run
```

Or drive a server directly:

```sh
python3 run_doceval.py --vault /private/tmp/doceval-vault --run \
  --api ollama --upstream http://192.168.68.104:11434 \
  --model qwen3.6:35b-mlx-32k --num-ctx 32768 --dry-run
```

`--api` is `openai` (`/v1/chat/completions`), `ollama` (`/api/chat`) or
`anthropic` (`/v1/messages`). mlx_lm.server speaks only Chat Completions, so use
`--api openai` for it; there is no API translation here, exactly as in
`run_eval.py`. Drop `--dry-run` to send. `--tasks A-1,A-3` runs a subset.

## Server ownership

This harness **never starts, stops or unloads a server**, and never edits CLI
configuration. For `--run` the operator owns the server. An existing
`/private/tmp/llm-server.lock` is recorded in the report and warned about;
`--require-free-lock` turns it into an abort. The lock is never created or
deleted here -- that remains `run_eval.py`'s discipline.

## Report

`report.json` holds every task's metrics and violations plus a `summary.headline`
with the figures that matter for this use case: A-3 fabrication count, A-2 PII
recall / leaked list / over-masked list, A-1 recall and precision, A-4 false
positives, A-6 invented tags, A-7 violation count. A task that was not run reads
`null`, never `0`. Per-task `usage` is `{input, output, seconds}`, taken from the
server in `--run` mode or from an optional `<task>.usage.json` in `--grade` mode;
absent values are null rather than guessed.

## The token ceiling

`--max-tokens` defaults to 16384. It is a ceiling, not a budget: a reply that
stops on its own costs nothing, so set it well above what any legitimate answer
needs. Use `--timeout` to bound wall-clock time instead.

The answers themselves are short -- under 1000 tokens each -- but thinking is
not. On the first real run a ceiling of 2048 produced **zero-byte replies** from
every thinking model: deliberation consumed the whole allowance before a single
character of the answer appeared. At 8192 the largest observed reply was 5810
tokens (A-3), so that ceiling held with only 1.4x of headroom.

The report carries `finish_reason` and a `truncated` flag per task, plus
`truncated_ids` and `max_output_tokens_seen` in the summary. A truncated result
is reported apart from an ordinary failure, because the ceiling cutting off a
reply says nothing about the model. Check `max_output_tokens_seen` after a run:
if it approaches the ceiling, raise it and rerun rather than reading the scores.

## Known limitations

- Fabrication detection covers numerals, Latin-script tokens and wikilink names.
  **A fabricated Japanese proper noun is not caught.**
- Integers 0-10 are excluded from fabrication by default, because counting words
  ("3つの記録") would otherwise register as invented numbers.
- A-2 scores leakage by substring, including name parts and email local parts.
  A model that paraphrases a name rather than masking it is not detected.
- A-4 accepts a contradiction report when the entry names both files, both
  values and the item keyword; it does not check the explanation's wording.
- Every task is one prompt, one trial. Multiple trials and multiple task
  variants are needed before any ranking is read as a model property.

## Self-test

```sh
python3 selftest.py
```

Builds the vault in a temporary directory, feeds each grader a perfect answer
and a deliberately flawed one, and asserts the perfect set passes everything
while the flawed set trips the intended predicate, with targeted checks on
partial leaks, over-masking, fabrication count, false-positive contradictions,
invented tags, bullets and cross-section leakage. Run it after editing
`build_vault.py`, `tasks.py` or `graders.py`. It contacts no server.

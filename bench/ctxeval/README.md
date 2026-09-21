# Long-context evaluation (task set E)

Answers the question the other sets cannot: **where does quality break as the
document gets longer?** Sets A-C all use inputs of 400-900 tokens, while real
work means minutes of meeting notes or a PDF of measurements.

**Run against 3 configurations as of 2026-09-21** (Qwen3.6 GGUF 90/90, MLX
89/90, Ornith 23/24, all near-ceiling up to ~26k tokens). See
`../INVOCATIONS.md` for the exact commands and the runtime-specific gotchas
(GPU memory limits, session-cache disk pressure) hit along the way.

## Why not RULER or Needle-in-a-Haystack

The task taxonomy here is borrowed from RULER -- single needle, multiple
needles, multi-hop tracing, aggregation, distractors -- because that design is
sound and worth copying. The data is not.

Published haystacks are English. Japanese tokenises differently, so an English
32k document is not a Japanese 32k document, and the question being asked is
how *these* documents behave on *this* machine. Generating the filler also
removes contamination and makes every answer exact. What is lost is
comparability with published numbers, which matters little here: published
figures are for cloud models at 128k, not for a 32GB Mac deciding whether 16k
is usable.

## The canary is the point

A server can silently drop the front of an over-long input. This machine has
already seen it: Ollama accepted 19,305 tokens into a 16384 context and
answered normally, and the logs could not say whether it truncated or shifted.

So every document opens with a管理番号 (`CN-nnnn-nnnn`) and every task asks for
it alongside the answer. A model that answers a needle placed late in the text
but cannot report the canary was not reading the document that was sent.

Such a case is reported as **inconclusive, not as a model failure** --
`answer_correct` stays true, `canary_ok` is false, and `passed` is false. The
summary lists these separately so they are never read as a capability result.

## Tasks

| id | task | what it isolates |
|---|---|---|
| E-1 | 単一針 | retrieval at a controlled depth; the position curve |
| E-2 | 複数針 | recall when three facts must all be found |
| E-3 | 多段 | following a pointer from one part of the document to another |
| E-4 | 集計 | arithmetic over marked values scattered through the text |
| E-5 | 干渉 | choosing the 【確定】 item among three 【取消】 lookalikes |
| E-6 | 棄権 | saying nothing is there, when nothing is there |

E-1, E-3 and E-5 run across every depth; the others sit at the middle. E-6 is
the abstention case: the document contains no serial at all, and inventing one
is the failure. Pair its result with E-1 at the same length -- a model that
passes E-6 by always answering null has simply stopped answering.

## Running it

A full grid is 5 lengths x 5 depths x 3 needle tasks plus 3 more tasks = 90
requests, and a 24k prefill alone costs about a minute. Start small:

```sh
python3 run_ctxeval.py --build /private/tmp/ctx-hay \
  --lengths 1000 8000 --depths 0.0 0.5 1.0 \
  --run --api ollama --upstream http://127.0.0.1:11434 \
  --model qwen3.6:35b-a3b-q4_K_M-32k --num-ctx 32768 \
  --answers /private/tmp/ctx-run --dry-run
```

Or split execution from grading, as with the other suites:

```sh
python3 run_ctxeval.py --build /private/tmp/ctx-hay --emit /private/tmp/ctx-run
# run the prompts elsewhere, save replies as <case id>.txt
python3 run_ctxeval.py --haystack /private/tmp/ctx-hay --grade /private/tmp/ctx-run
```

Lengths are requested in approximate tokens and realised as characters through
`--chars-per-token` (1.4 for Japanese by default). **The number that matters is
the one the server reports**, recorded per case as `usage.input` and summarised
as `actual_input_tokens`. Set `--num-ctx` high enough that the context window
is not the thing being measured, unless that is the experiment.

`--max-tokens` defaults to 2048 here because the answers are a few dozen tokens.
Raise it for thinking models, which spend thousands before answering.

## Report

`pass_rate_by_length` is the curve worth looking at first, `pass_rate_by_depth`
second -- a dip at one depth with a flat length curve means position, not
capacity. `canary_failures` and `answer_correct_but_canary_lost` qualify both:
if those are non-empty, the length axis is not what it appears to be.

## Known limitations

- Filler is synthetic measurement-log prose. Real documents have structure,
  tables and inconsistent formatting that this does not reproduce.
- `--chars-per-token` is an estimate for sizing only; actual tokens vary by
  tokeniser, which is why they are recorded rather than assumed.
- Needle serials are distinctive (`RX-nnnn`), which makes retrieval easier than
  finding a fact phrased in ordinary prose. The curve's shape is informative;
  its absolute height is optimistic.
- One trial per case. No repeats, so a single miss and a systematic failure look
  alike.

## Self-test

```sh
python3 selftest.py
```

Verifies the generated documents actually contain each needle exactly once and
that abstention cases contain no serial at all, then that perfect answers pass,
wrong answers fail with the intended violation (including picking a withdrawn
job and inventing an answer), and that a right answer with a lost canary is
reported as truncation rather than success.

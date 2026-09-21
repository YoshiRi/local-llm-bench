# Investigation evaluation (task set B)

Measures shell-driven investigation: finding a file from a vague hint, and
reading machine state. Coding ability does not predict this -- see
`ローカルLLM 次の評価セット設計` in the vault.

**Run against 5 configurations as of 2026-09-21** (Qwen3.6 GGUF/MLX, Ornith,
Gemma4, Coder DWQ v2) via `--run` with `claude -p`. See `../INVOCATIONS.md`
for the exact commands.

## How the answers are made deterministic

Asking about the real machine would make grading depend on live state, so the
sandbox supplies both halves of the environment:

- `root/home/` a synthetic file tree. `find`, `grep`, `du`, `shasum` and
  friends work on it normally; every answer follows from planted content.
- `root/bin/` stub executables (`sysctl`, `lsof`, `netstat`, `ifconfig`,
  `diskutil`, `df`) that print fixed output. Prepend this directory to `PATH`
  so ordinary command knowledge still applies while the answers stay fixed.

Nothing reads or reports the real machine's state, and `build_sandbox.py` is
deterministic.

**The stubs only win while they are reached by bare name.** `/usr/sbin/lsof`
bypasses them and reads the real machine, which invalidates B-4..B-6. The
prompt says so, and `stub_bypass_count` in the report counts it when a
transcript is supplied. Treat a trial with bypasses as unusable for those
tasks rather than as a failure.

## Tasks

| id | title | layer | what it exercises |
|---|---|---|---|
| B-1 | ヒントからファイル特定 | L1/L2 | content search, with a filename decoy that defeats `find -name` |
| B-2 | サイズ上位ファイル | L1 | size listing in exact bytes, ordered |
| B-3 | 重複ファイル検出 | L2 | hashing; a same-size one-byte-different file is planted |
| B-4 | メモリ・GPU割当上限 | L1 | `sysctl` for `iogpu.wired_limit_mb` and `hw.memsize` |
| B-5 | 待ち受けと公開範囲 | L2 | listening sockets, and judging LAN exposure vs loopback |
| B-6 | 外付けディスクの状態 | L1 | mount point and free space, picking the right `df` row |

Layers: L0 protocol / L1 knowledge / L2 observe-and-branch / L3 non-destructive.

Every task is **read-only**. Answers are written outside the sandbox, and the
grader hashes the tree: any modification is an L3 violation, detected without
needing a log. Git tasks (revert by bisect, untracking a committed secret,
conflict resolution) are designed in the vault note but not implemented here.

## Three modes

```sh
python3 run_cmdeval.py --build-sandbox /private/tmp/cmdeval-sbx \
                       --emit /private/tmp/cmdeval-run
# HOWTO.txt prints the PATH export and cwd; run each prompt with your CLI
python3 run_cmdeval.py --sandbox /private/tmp/cmdeval-sbx \
                       --grade /private/tmp/cmdeval-run \
                       --transcript /private/tmp/cmdeval-run/B-1.jsonl
```

`--run` executes a command template you supply; it does not invent CLI flags:

```sh
python3 run_cmdeval.py --sandbox /private/tmp/cmdeval-sbx --run \
  --answers /private/tmp/cmdeval-run \
  --cli-command 'codex -a never exec --ignore-user-config --ignore-rules -s workspace-write {prompt}' \
  --dry-run
```

`{prompt}` and `{prompt_file}` are substituted. The child runs with the
sandbox as cwd and `root/bin` prepended to `PATH`. Drop `--dry-run` to execute.
The example flags are copied from the vault's Codex note and have not been
exercised through this harness; verify them yourself before a real trial.

Do not rebuild the sandbox between tasks of one trial -- grading compares its
hash, and a modification is the result being measured. Rebuild between trials.

## Report

`report.json` carries per-task metrics and violations, plus run-level signals:

- `tree_intact` -- false means the agent wrote to a read-only area (L3)
- `shell_calls`, `nonzero_exits` -- L2, the observe-and-branch signal
- `dangerous_count` with the matching commands -- L3 (`rm -rf`, `git reset
  --hard`, `sudo`, raw device writes, recursive permission changes, ...)
- `stub_bypass_count` -- trial validity, not model quality

Without `--transcript` every command metric is `null`, never `0`.

## Known limitations

- Transcript parsing is best-effort across Codex `--json` and Claude
  `--output-format stream-json`; it collects any object carrying a `command`
  field. Counts are indicative and should be reported as such.
- Exit codes are collected wherever they appear in the transcript and are not
  matched back to individual commands.
- The sandbox does not confine the agent: it can still read the real
  filesystem outside the tree. Pair it with the CLI's own sandbox flags.
- `selftest.py`'s reference solution uses macOS `stat -f` and `shasum`.
- One prompt, one trial per task. No ranking should be read as a model
  property without repeats.

## Self-test

```sh
python3 selftest.py
```

Builds a sandbox in a temporary directory and **actually solves every task with
real shell commands** through the PATH stubs, asserting the reference answers
pass -- this proves the tasks are solvable as intended and the stubs are
reachable. Then it checks that deliberately wrong answers fail (including the
filename decoy for B-1 and the near-duplicate trap for B-3), and that tree
modification, dangerous commands and stub bypass are all detected.

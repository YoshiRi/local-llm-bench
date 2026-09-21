# Local CLI evaluation harness

This top-level `run_eval.py` (the original general-purpose CLI harness) has
not been run for real — only syntax-checked and exercised with `--dry-run`;
real CLI/provider integrations remain unverified here. Existing Codex settings
are never edited. **The four task-specific suites below (`doceval/`,
`cmdeval/`, `giteval/`, `ctxeval/`) are separate harnesses and have been run
extensively** — see each one's own README and `INVOCATIONS.md`.

```sh
python3 run_eval.py --cli codex --provider ollama \
  --model qwen3.6:35b-mlx-32k --trials 3 \
  --upstream http://127.0.0.1:11434 \
  --cli-bin /Applications/ChatGPT.app/Contents/Resources/codex --dry-run
```

Choose `--cli aider` or `--cli claude` to print the alternative command.
`--provider mlx` requires an explicit foreground `--server-command` for real
runs. Model paths must refer to existing downloads. Codex requires Responses;
Claude requires Anthropic Messages. The logging proxy does not translate APIs.
Do not point either CLI directly at an incompatible server and expect conversion.

The harness atomically creates `/private/tmp/llm-server.lock` BEFORE starting any
server or contacting Ollama. An existing lock causes waiting (default 3600s),
never deletion. The file records model, owner PID, start time and managed server
PID. Do not remove another session's lock. All real runs require exclusive GPU
ownership, even when the Ollama daemon is already running. Preloaded models are
rejected, not unloaded. A successful run unloads its model; an interrupted or
failed Ollama CLI retains the lock because an upstream request can outlive its
client. Inspect the runner and stop it before manually releasing that lock.
No launchd definitions are modified. Managed servers must stay in the foreground.

`--dry-run` does not acquire a lock, start processes, access HTTP, clone a repo,
or create output directories. It can run while another session owns the GPU.
The printed environment overrides contain only dummy local credentials.

Each real trial clones the seed at the pinned commit, invokes the selected CLI,
then runs unittest, a structured extra-input probe, and git diff against the seed
(including changes a CLI may have committed). `real_seconds` measures only the
CLI process, not clone/startup/verification. Cold model loading inside the first
request is included. Test changes and untracked files are reported separately.

One `report.json` contains all trials, with an individual `result.json` and
request/log artifacts in each trial directory. Request count counts POST body
files, including retries, not GET model discovery. Log metrics use the trial's
byte window with inode/truncation checks. Missing logs yield nulls. MLX's
`Prompt Cache: N sequences` is an inventory, NOT a cache hit count. Ollama peak
is the maximum logged GiB value, not system RAM or RSS. Supply `--server-log`
when the daemon log is elsewhere; remote server logs cannot be read automatically.

The Codex default disables plugins/apps and other nonessential capabilities.
It does not force `apply_patch`: fallback model metadata may omit that tool.
Keep this caveat when comparing with Claude/Aider. CLI versions and upstream
compatibility should be checked before removing `--dry-run`. Extra flags may be
passed as `--cli-arg=--some-flag`. No automatic model downloads are performed
by the harness; an explicit server command remains the operator's responsibility.

`tool_breakdown.py REQUEST.json` analyzes captured tool definitions offline.
`diagnose_codex.py` only runs version checks, with a kill/reap timeout; its
network-denied case uses a process-scoped macOS sandbox, not a system setting.

## Document-processing set (`doceval/`)

`doceval/` evaluates task set A -- Japanese document processing against a
synthetic vault -- and is independent of this CLI harness. Its prompts inline
the notes, so no CLI, tool protocol, shell or git is involved. It never starts
or stops a server and never creates or deletes the GPU lock; it only reports the
lock's presence, or aborts on `--require-free-lock`. Use `--emit` to write the
prompts and `--grade` to score replies produced elsewhere, or `--run` to drive a
server directly. `doceval/selftest.py` verifies the graders offline. See
`doceval/README.md`.

## Investigation set (`cmdeval/`)

`cmdeval/` evaluates task set B -- shell-driven investigation -- against a
synthetic sandbox: a planted file tree plus stub `sysctl`/`lsof`/`netstat`/
`ifconfig`/`diskutil`/`df` reached by PATH, so answers are deterministic and
the real machine is never inspected. Every task is read-only; the grader hashes
the tree and reports any modification as an L3 violation. With a CLI transcript
it also reports shell-call count, nonzero exits, dangerous commands and stub
bypass. `--run` executes a command template you supply rather than inventing CLI
flags. `cmdeval/selftest.py` solves every task with real shell commands to prove
they are solvable, then checks the graders reject wrong answers. See
`cmdeval/README.md`.

## Git set (`giteval/`)

`giteval/` completes set B with three git tasks (find and revert a breaking
commit, untrack a committed secret, resolve a merge conflict). Commit hashes are
reproducible because author, committer and dates are pinned, so the answer key
names the real breaking commit and branch tips. These repositories are meant to
be modified; what is graded is the end state AND that the seed HEAD is still an
ancestor of the final HEAD, which is what `reset --hard` and `rebase` destroy.
It shares the dangerous-command scanner and transcript parser with `cmdeval/`.
`giteval/selftest.py` solves all three with real git operations and checks that
destructive shortcuts are rejected. See `giteval/README.md`.

## Long-context set (`ctxeval/`)

`ctxeval/` measures where quality breaks as the document grows -- the axis every
other suite misses, since they all use 400-900 token inputs. The task taxonomy
is borrowed from RULER; the Japanese filler, needles and answer keys are
generated here, so the documents match the real use case and cannot be
contaminated. Every document opens with a canary that each task must report
alongside its answer, which is how a silently front-truncated input is told
apart from a model failure and reported as inconclusive. HTTP transport and the
truncation rule come from `doceval/transport.py`, shared so the two suites
cannot drift. See `ctxeval/README.md`.

## Typed-decision set (`jeveval/`)

`jeveval/` asks whether a small decision-only model (Jev-style: probabilities
over allowed options, no generated text) can act as a router/guardrail/scorer
in front of the big models. Three tasks with machine-checkable keys: the
`domain/*` tag of a real vault note, which of two sentences is natural
Japanese, and whether a line contains planted PII. Backend under test is SemIf
(MLX, Qwen3.5-4B 4-bit). Results and how to run: `jeveval/README.md`.

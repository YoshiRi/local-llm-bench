# Invocation cookbook

Working CLI invocations for each harness against each runtime, collected from
actual runs (2026-09-19 through 2026-09-21) rather than written speculatively.
All servers are started/stopped under `/private/tmp/llm-server.lock` (see the
top-level `README.md`); none of the harnesses touch that file themselves
except by reporting its presence.

## Runtimes

Three server processes were used this project, each with a different API
surface and a different way to control "thinking" and sampling:

| Runtime | Serves | Models used |
| --- | --- | --- |
| Ollama | Anthropic Messages, OpenAI Responses, OpenAI Chat Completions (all native) | Qwen3.6 GGUF/MLX, Gemma4 |
| `mlx_lm.server` | OpenAI Chat Completions only | Coder DWQ v2, Qwen3.6 mxfp4 |
| `mtplx serve` | OpenAI Chat Completions + Anthropic Messages (native) | Ornith-1.5 |

### Sampling settings: the one mistake to not repeat

Every model card specifies its own recommended `temperature`/`top_p`/`top_k`.
**`temperature=0` is not a safe default** — it caused a multi-hour false
negative on Gemma4 (infinite "thinking", never terminated) before the card's
own recommendation (`temperature=1.0, top_p=0.95, top_k=64`) was checked and
applied. Check the card before the first real run of any new model, not after
a confusing result.

| Model | Recommended | Flag(s) |
| --- | --- | --- |
| Qwen3.6 (GGUF/MLX/mxfp4, `qwen3_5_moe`) | `temp=1.0, top_p=0.95, top_k=20, presence_penalty=1.5` | Ollama Modelfile default matches; `mlx_lm.server --temp 1.0 --top-p 0.95 --top-k 20` |
| Coder DWQ v2 (Instruct, no thinking) | `temp=0.7, top_p=0.8, top_k=20, repetition_penalty=1.05` | `mlx_lm.server --temp 0.7 --top-p 0.8 --top-k 20` (no `repetition_penalty` flag exists — known gap) |
| Ornith-1.5 | `temp=0.6, top_p=0.95, top_k=20` | `mtplx serve --default-temperature 0.6` |
| Gemma4-26B-A4B | `temp=1.0, top_p=0.95, top_k=64`, "for all use cases" | Ollama Modelfile default matches |

`doceval`/`ctxeval`/`cmdeval`/`giteval` only expose `--temperature` as a CLI
knob (no `top_p`/`top_k`/`repetition_penalty`). When a harness run and a
model's full recommended settings diverge, note it in the write-up — this has
been a real source of noise (see the GGUF vs MLX doceval flip after the
sampling fix).

### Disabling "thinking" (avoids output-budget truncation)

Thinking models can spend the entire `max_tokens` budget on the reasoning
trace and never emit final content — `ctxeval` reports this as `OUTPUT
TRUNCATED` (not a hard failure); `doceval` currently raises `KeyError('content')`
on it (harness gap, not fixed yet). Two ways to avoid it:

1. **Raise `max_tokens`.** Simplest. `ctxeval` defaults to 2048 for this reason
   — raise it for any thinking model. 8192 has been generous enough in practice.
2. **Disable thinking for the request**, verified working per runtime:
   - Ollama native API: `{"think": false}` in the request body. Simpler than
     the Anthropic-compat `{"thinking":{"type":"disabled"}}` byte-preserving
     proxy trick used earlier for Claude Code — use the native field directly
     when the client is a raw HTTP/Ollama call rather than Claude Code itself.
   - `mlx_lm.server`: `{"chat_template_kwargs": {"enable_thinking": false}}` in
     the request body (per-request), or `--chat-template-args
     '{"enable_thinking":false}'` at server launch (static default).
   - `mtplx serve`: `--reasoning off` or `--reasoning-effort low` at launch.

## doceval (task set A, document processing)

```sh
cd bench/doceval
python3 run_doceval.py --build-vault /private/tmp/doceval-vault

# Ollama (GGUF/MLX/Gemma4)
python3 run_doceval.py --vault /private/tmp/doceval-vault --run \
  --api ollama --upstream http://127.0.0.1:11434 \
  --model qwen3.6:35b-a3b-q4_K_M-32k --temperature 1.0 \
  --timeout 300 --output /private/tmp/doceval-run

# mlx_lm.server (Coder DWQ v2, mxfp4 — start the server first, matching card settings)
python3 run_doceval.py --vault /private/tmp/doceval-vault --run \
  --api openai --upstream http://127.0.0.1:8081 \
  --model default_model --temperature 0.7 \
  --max-tokens 4096 --timeout 300 --output /private/tmp/doceval-run
```

## cmdeval (task set B, shell investigation) and giteval (B-7..B-9, git)

Both drive an actual CLI (`claude -p`, not the harness talking to the API
directly), so the model connects through Claude Code's own provider switch.

```sh
# Point Claude Code at the local server BEFORE invoking the harness
export ANTHROPIC_BASE_URL=http://127.0.0.1:11434   # Ollama; use the mlx_lm.server bridge port for Coder/mxfp4
export ANTHROPIC_AUTH_TOKEN=ollama                  # any non-empty value

cd bench/cmdeval
python3 run_cmdeval.py --build-sandbox /private/tmp/cmdeval-sbx
python3 run_cmdeval.py --sandbox /private/tmp/cmdeval-sbx --run \
  --cli-command 'claude -p {prompt} --model qwen3.6:35b-a3b-q4_K_M-32k --permission-mode acceptEdits --allowedTools Bash,Read,Glob,Grep,Write --output-format json' \
  --answers /private/tmp/cmdeval-run --timeout 400

cd ../giteval
python3 run_giteval.py --build-repos /private/tmp/giteval-repos
python3 run_giteval.py --repos /private/tmp/giteval-repos --run \
  --cli-command 'claude -p {prompt} --model qwen3.6:35b-a3b-q4_K_M-32k --permission-mode acceptEdits --allowedTools Bash,Read,Glob,Grep,Write,Edit --output-format json' \
  --answers /private/tmp/giteval-run --timeout 400
```

**Forgetting `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` fails fast and
misleadingly**: `claude -p` falls back to the real Anthropic API, which
rejects a local model name in ~3 seconds with `[claude-code:unrecognized_model]`
— every task fails instantly. If every task fails in a couple of seconds each,
check the env vars before suspecting the model.

`giteval` needs `Edit` in `--allowedTools` (in addition to `cmdeval`'s set) —
B-9 (conflict resolution) edits file content directly, not just via shell.

## ctxeval (task set E, long context)

```sh
cd bench/ctxeval
python3 run_ctxeval.py --build /private/tmp/ctx-hay \
  --lengths 1000 4000 8000 16000 24000 --depths 0.0 0.25 0.5 0.75 1.0

# Ollama
python3 run_ctxeval.py --haystack /private/tmp/ctx-hay --run \
  --api ollama --upstream http://127.0.0.1:11434 \
  --model qwen3.6:35b-a3b-q4_K_M-32k --num-ctx 32768 --temperature 1.0 \
  --timeout 400 --answers /private/tmp/ctx-run

# mtplx serve (Ornith) — --ssd-session-cache off is load-bearing, see below
python3 run_ctxeval.py --haystack /private/tmp/ctx-hay --run \
  --api openai --upstream http://127.0.0.1:8082 \
  --model <mtplx model id> --temperature 0.6 \
  --timeout 300 --answers /private/tmp/ctx-run
```

Start with the small grid (`--lengths 1000 8000 --depths 0.0 0.5 1.0`, 24
cases) before the full one (90 cases, the 24000-token tier alone takes
minutes per case).

## Server launch commands actually used

```sh
# Ollama — bound to 0.0.0.0 (LAN + Tailscale + localhost) via
# ~/Library/LaunchAgents/com.yoshiri.ollama-host.plist; OLLAMA_HOST=0.0.0.0:11434
# After changing the plist: launchctl bootout/bootstrap it, then fully quit and
# relaunch Ollama.app — a running `ollama serve` caches OLLAMA_HOST at its own
# startup and does not pick up a later `launchctl setenv`.

# mlx_lm.server (Coder DWQ v2 example — HF cache, or point --model at an SSD path directly)
mlx_lm.server --model mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2 \
  --host 127.0.0.1 --port 8081 --trust-remote-code --max-tokens 8192 \
  --temp 0.7 --top-p 0.8 --top-k 20

# mtplx serve (Ornith, direct from external SSD archive — no copy to internal disk needed)
/Users/yoshiri/Documents/local-llm/.venv-mtplx/bin/mtplx serve \
  --model /Volumes/ExtremeSSD/LocalLLM/backup-20260919-235029/MLX/wang-yang--Ornith-1.5-35B-A3B-MTPLX-4bit/44d09b73035cb12dcb474c3c0d1c8629acdcf5ba \
  --host 127.0.0.1 --port 8082 --no-auth --max-tokens 8192 \
  --default-temperature 0.6 --depth 2 --unsafe-force-unverified --yes \
  --ssd-session-cache off

# mtplx serve for remote clients over LAN/Tailscale (dsh / Aider / raw chat — NOT Claude Code).
# A non-localhost --host REQUIRES --api-key (--no-auth is refused). --kv-quant q8
# halves KV memory so --context-window 49152 fits the 24G engine budget for a
# single large request (verified: 41.5k tokens, correct answer, no OOM).
#
# BUT Claude Code sessions do not work against this on the 32GB machine, whatever
# the window: its ~19k-token per-turn prefill drives MTPLX's allocator past 100%
# (pressure_trim, remote clients get 507 "insufficient memory ... during prefill"),
# the prefix cache is evicted every turn, and a trivial 8-turn task took 25 min
# locally. Weights 19.4G + 19k prefill + KV + scratch simply exceed the budget.
# Use Ollama Qwen3.6 MLX/GGUF for Claude Code; reserve Ornith for clients whose
# prompts are a few k tokens, where its 2-3x speed actually shows.
/Users/yoshiri/Documents/local-llm/.venv-mtplx/bin/mtplx serve \
  --model /Volumes/ExtremeSSD/LocalLLM/backup-20260919-235029/MLX/wang-yang--Ornith-1.5-35B-A3B-MTPLX-4bit/44d09b73035cb12dcb474c3c0d1c8629acdcf5ba \
  --model-id ornith --host 0.0.0.0 --port 8082 --api-key <choose-one> \
  --max-tokens 8192 --default-temperature 0.6 --depth 2 --unsafe-force-unverified --yes \
  --ssd-session-cache off --kv-quant q8 --context-window 49152
```

Two infra gotchas worth remembering before re-running any of the above:

- **`iogpu.wired_limit_mb` resets to 0 on reboot.** Models near or above
  ~20GB (Qwen3.6 MLX, Ornith) then fail to load with "insufficient memory"
  errors that look like a model problem but aren't. Fix: `sudo sysctl
  iogpu.wired_limit_mb=26624`, then **restart Ollama** specifically (it caches
  the limit at its own startup; MTPLX and `mlx_lm.server` do not need a
  restart).
- **MTPLX's `--ssd-session-cache` defaults on** and writes to
  `~/.mtplx/session-bank` on the *internal* disk regardless of where the model
  itself lives. On a machine with little internal free space this causes
  intermittent `HTTP 507 Insufficient Storage` under back-to-back long-context
  requests. Pass `--ssd-session-cache off` unless internal disk headroom is
  confirmed ample.

Always launch a foreground server under `nohup ... &` with a direct binary
path (e.g. `/Users/yoshiri/.local/bin/mlx_lm.server`, or the venv's binary
directly rather than `source .venv/bin/activate && ...`) — the latter form has
been intermittently rejected by this environment's own safety layer for
unclear reasons; the direct-path form has not been.

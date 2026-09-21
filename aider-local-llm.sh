#!/usr/bin/env bash
set -euo pipefail

export OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://127.0.0.1:11434}"

exec /Users/yoshiri/.local/bin/aider \
  --no-check-update \
  --analytics-disable \
  --no-show-model-warnings \
  --model ollama_chat/qwen3.6:35b-a3b-q4_K_M \
  --weak-model ollama_chat/qwen3.6:35b-a3b-q4_K_M \
  --editor-model ollama_chat/qwen3.6:35b-a3b-q4_K_M \
  "$@"

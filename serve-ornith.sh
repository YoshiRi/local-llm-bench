#!/usr/bin/env bash
# Ornith-1.5 (MTPLX) を LAN/Tailscale 向けにホストする。
#   serve-ornith.sh start   # Ollamaのモデルをアンロードしてから起動（同時ロード不可のため）
#   serve-ornith.sh stop
#   serve-ornith.sh status
# 別PCのdsh設定例:
#   providers.ornith: {apiKeyEnv: ORNITH_API_KEY, api: openai-completions,
#                      baseURL: http://<このMacのIP>:8082/v1, models: [{id: ornith}]}
# Claude Codeの対話セッションには使わない（19kトークン/ターンのprefillでメモリ不足）。
set -euo pipefail

MODEL_DIR="${ORNITH_MODEL_DIR:-/Volumes/ExtremeSSD/LocalLLM/backup-20260919-235029/MLX/wang-yang--Ornith-1.5-35B-A3B-MTPLX-4bit/44d09b73035cb12dcb474c3c0d1c8629acdcf5ba}"
MTPLX="${MTPLX_BIN:-$HOME/Documents/local-llm/.venv-mtplx/bin/mtplx}"
PORT="${ORNITH_PORT:-8082}"
API_KEY="${ORNITH_API_KEY:-ornith-local}"   # tailnet/LAN内限定の形式的なキー。非localhost bindではMTPLXが必須にする
LOCK=/private/tmp/llm-server.lock
LOG="${ORNITH_LOG:-/private/tmp/ornith-serve.log}"
OLLAMA=http://127.0.0.1:11434

running_pid() { pgrep -f "mtplx.server.openai.*--port $PORT" | head -n1 || true; }

unload_ollama() {
  local names
  names=$(curl -s "$OLLAMA/api/ps" 2>/dev/null | python3 -c 'import json,sys; print("\n".join(m["name"] for m in json.load(sys.stdin)["models"]))' 2>/dev/null || true)
  [ -z "$names" ] && return 0
  echo "Ollamaのロード中モデルをアンロード: $names"
  while read -r n; do
    [ -n "$n" ] && curl -s "$OLLAMA/api/generate" -d "{\"model\":\"$n\",\"keep_alive\":0}" >/dev/null
  done <<<"$names"
  for _ in $(seq 1 30); do
    [ "$(curl -s "$OLLAMA/api/ps" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["models"]))')" = "0" ] && return 0
    sleep 2
  done
  echo "警告: Ollamaのモデルがアンロードされない。別PCのセッションが動いていないか確認" >&2
  return 1
}

start() {
  if [ -n "$(running_pid)" ]; then echo "既に起動中 (pid $(running_pid))"; status; return 0; fi
  if [ -f "$LOCK" ]; then echo "GPUロックあり: $(cat "$LOCK")" >&2; echo "他のサーバーが動作中。先に停止するか $LOCK を確認" >&2; exit 1; fi
  [ -d "$MODEL_DIR" ] || { echo "モデルが見つからない: $MODEL_DIR（外付けSSDはマウント済み？）" >&2; exit 1; }
  unload_ollama
  echo "model=Ornith-1.5-MTPLX owner=serve-ornith.sh started=$(date -u +%Y-%m-%dT%H:%M:%S) port=$PORT" > "$LOCK"
  nohup "$MTPLX" serve --model "$MODEL_DIR" --model-id ornith \
    --host 0.0.0.0 --port "$PORT" --api-key "$API_KEY" \
    --max-tokens 8192 --default-temperature 0.6 --depth 2 \
    --unsafe-force-unverified --yes --ssd-session-cache off \
    > "$LOG" 2>&1 &
  echo "起動中 (pid $!)、ログ: $LOG"
  for _ in $(seq 1 60); do
    grep -q "MTPLX is ready" "$LOG" 2>/dev/null && break
    grep -qE "^error:|Traceback" "$LOG" 2>/dev/null && { echo "起動失敗:" >&2; tail -5 "$LOG" >&2; rm -f "$LOCK"; exit 1; }
    sleep 3
  done
  status
}

stop() {
  local pid; pid=$(running_pid)
  if [ -n "$pid" ]; then kill "$pid"; sleep 2; echo "停止 (pid $pid)"; else echo "起動していない"; fi
  [ -f "$LOCK" ] && grep -q "serve-ornith.sh" "$LOCK" && rm -f "$LOCK"
  return 0
}

status() {
  local pid; pid=$(running_pid)
  if [ -z "$pid" ]; then echo "Ornith: 停止中"; return 0; fi
  local lan ts
  lan=$(ipconfig getifaddr en0 2>/dev/null || ifconfig | grep -oE "inet 192\.168\.[0-9.]+" | head -n1 | cut -d" " -f2 || true)
  ts=$(tailscale ip -4 2>/dev/null | head -n1 || true)
  echo "Ornith: 起動中 (pid $pid, port $PORT, context $(grep -oE 'Context window: [0-9]+' "$LOG" | tail -n1 | grep -oE '[0-9]+'))"
  echo "  localhost : http://127.0.0.1:$PORT/v1"
  [ -n "$lan" ] && echo "  LAN       : http://$lan:$PORT/v1"
  [ -n "$ts" ]  && echo "  Tailscale : http://$ts:$PORT/v1"
  echo "  API key   : $API_KEY  (dsh: apiKeyEnv に入れる / Claude Code: ANTHROPIC_AUTH_TOKEN)"
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status}" >&2; exit 2 ;;
esac

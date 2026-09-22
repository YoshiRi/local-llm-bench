#!/usr/bin/env bash
# dsh Web UI を Mac mini 上で動かし、Tailscale Serve で tailnet 内（スマホ等）に公開する。
#   serve-dsh-web.sh start [workspace-dir]   # 既定: ~/Documents/dsh-workspace
#   serve-dsh-web.sh stop
#   serve-dsh-web.sh status
# dsh web は安全上 127.0.0.1 にしか bind できない（0.0.0.0 は明示的に拒否される）ため、
# 127.0.0.1:$PORT で起動し、Tailscale Serve の HTTPS プロキシを手前に置く。
# ブラウザは https://<このMacのMagicDNS名>/?token=... で開く（IP直は不可。初回は証明書発行で数秒待つ）。
# 推論先は ~/.dsh/settings.yaml の agent-default-model（Ornith なら serve-ornith.sh start が先）。
set -euo pipefail

PORT="${DSH_WEB_PORT:-3081}"
LOG=/private/tmp/dsh-web.log
WS="${2:-$HOME/Documents/dsh-workspace}"
export ORNITH_API_KEY="${ORNITH_API_KEY:-ornith-local}"
export OLLAMA_API_KEY="${OLLAMA_API_KEY:-ollama}"

dns_name() { tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'; }
running_pid() { pgrep -f "dsh web --host 127.0.0.1 --port $PORT" | head -n1 || true; }

start() {
  if [ -n "$(running_pid)" ]; then echo "既に起動中 (pid $(running_pid))"; status; return 0; fi
  local name; name=$(dns_name)
  [ -n "$name" ] || { echo "Tailscaleに接続していない" >&2; exit 1; }
  mkdir -p "$WS"; cd "$WS"
  nohup npx --yes @deepseek-ai/dsh web --host 127.0.0.1 --port "$PORT" \
    --trusted-host "$name" --trusted-host "$name:443" --no-open > "$LOG" 2>&1 &
  for _ in $(seq 1 40); do grep -qE "dsh web: http|^error" "$LOG" 2>/dev/null && break; sleep 2; done
  grep -q "^error" "$LOG" && { cat "$LOG" >&2; exit 1; }
  tailscale serve --bg --https=443 "http://127.0.0.1:$PORT" >/dev/null
  status
}

stop() {
  tailscale serve --https=443 off 2>/dev/null || true
  local pid; pid=$(running_pid)
  [ -n "$pid" ] && { kill "$pid"; echo "停止 (pid $pid)"; } || echo "起動していない"
}

status() {
  local pid; pid=$(running_pid)
  [ -z "$pid" ] && { echo "dsh web: 停止中"; return 0; }
  local token; token=$(grep -oE 'token=[A-Za-z0-9_-]+' "$LOG" | tail -n1)
  echo "dsh web: 起動中 (pid $pid, workspace $WS)"
  echo "  スマホ/別PC(tailnet): https://$(dns_name)/?$token"
  echo "  このMac           : http://127.0.0.1:$PORT/?$token"
  tailscale serve status 2>/dev/null | sed 's/^/  /'
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status} [workspace-dir]" >&2; exit 2 ;;
esac

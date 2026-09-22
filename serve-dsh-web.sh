#!/usr/bin/env bash
# dsh Web UI を Mac mini 上で動かし、Tailscale IP でスマホ/別PC から開けるようにする。
#   serve-dsh-web.sh start [workspace-dir]   # 既定: ~/Documents/dsh-workspace
#   serve-dsh-web.sh stop
#   serve-dsh-web.sh status
#
# dsh web は安全上 127.0.0.1 にしか bind できない（0.0.0.0 も個別IPも拒否）ため、
# 127.0.0.1:$LOCAL_PORT で起動し、tcp-proxy.py を Tailscale IP:$PUBLIC_PORT に置いて転送する。
# --trusted-host に公開側の authority を渡さないと /api が拒否される。
#
# 開く時の注意: 認証 Cookie が SameSite=Strict なので、チャット等のリンクをタップして開くと
# 直後のリダイレクトで Cookie が送られず "authentication required" になる。
# URL をアドレスバーに貼り付けて開くか、エラー画面でアドレスバーから再読み込みする。
# Tailscale Serve (HTTPS + MagicDNS名) でも同じ現象が出る。トークンは再利用可。
set -euo pipefail

LOCAL_PORT="${DSH_WEB_PORT:-3081}"
PUBLIC_PORT="${DSH_WEB_PUBLIC_PORT:-3080}"
LOG=/private/tmp/dsh-web.log
PROXY_LOG=/private/tmp/dsh-web-proxy.log
WS="${2:-$HOME/Documents/dsh-workspace}"
HERE="$(cd "$(dirname "$0")" && pwd)"
export ORNITH_API_KEY="${ORNITH_API_KEY:-ornith-local}"
export OLLAMA_API_KEY="${OLLAMA_API_KEY:-ollama}"

ts_ip() { tailscale ip -4 2>/dev/null | head -n1; }
lan_ip() { ipconfig getifaddr en0 2>/dev/null || ifconfig | grep -oE "inet 192\.168\.[0-9.]+" | head -n1 | cut -d" " -f2 || true; }
web_pid() { pgrep -f "dsh web --host 127.0.0.1 --port $LOCAL_PORT" | head -n1 || true; }
proxy_pid() { pgrep -f "tcp-proxy.py --listen .*:$PUBLIC_PORT" | head -n1 || true; }

start() {
  if [ -n "$(web_pid)" ]; then echo "既に起動中"; status; return 0; fi
  local ip; ip=$(ts_ip)
  [ -n "$ip" ] || { echo "Tailscaleに接続していない" >&2; exit 1; }
  mkdir -p "$WS"; cd "$WS"
  nohup npx --yes @deepseek-ai/dsh web --host 127.0.0.1 --port "$LOCAL_PORT" \
    --trusted-host "$ip:$PUBLIC_PORT" $( [ -n "$(lan_ip)" ] && echo --trusted-host "$(lan_ip):$PUBLIC_PORT" ) \
    --no-open > "$LOG" 2>&1 &
  for _ in $(seq 1 40); do grep -qE "dsh web: http|^error" "$LOG" 2>/dev/null && break; sleep 2; done
  grep -q "^error" "$LOG" && { cat "$LOG" >&2; exit 1; }
  [ -n "$(proxy_pid)" ] || nohup python3 "$HERE/tcp-proxy.py" --listen "$ip:$PUBLIC_PORT" --target "127.0.0.1:$LOCAL_PORT" > "$PROXY_LOG" 2>&1 &
  sleep 1
  status
}

stop() {
  local p
  p=$(proxy_pid); [ -n "$p" ] && kill "$p" && echo "proxy 停止"
  p=$(web_pid); [ -n "$p" ] && { kill "$p"; echo "dsh web 停止"; } || echo "dsh web は起動していない"
  return 0
}

status() {
  local pid; pid=$(web_pid)
  [ -z "$pid" ] && { echo "dsh web: 停止中"; return 0; }
  local token; token=$(grep -oE 'token=[A-Za-z0-9_-]+' "$LOG" | tail -n1)
  echo "dsh web: 起動中 (pid $pid, workspace $WS)"
  echo "  スマホ/別PC(tailnet): http://$(ts_ip):$PUBLIC_PORT/?$token"
  [ -n "$(lan_ip)" ] && echo "  LAN (要: LAN側にもproxy)  : http://$(lan_ip):$PUBLIC_PORT/?$token"
  echo "  このMac             : http://127.0.0.1:$LOCAL_PORT/?$token"
  echo "  ※ リンクのタップではなく、URLをアドレスバーに貼って開く（SameSite=Strict）"
  [ -n "$(proxy_pid)" ] && echo "  proxy: 起動中 (pid $(proxy_pid))" || echo "  proxy: 停止中"
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|status} [workspace-dir]" >&2; exit 2 ;;
esac

# Local LLM

M4 Mac mini 32GBで動かすローカルLLMの運用スクリプトと評価ハーネス一式。目的は2つ:
(1) Claude Code/Codex/Aider向けのコーディング用途、(2) 社外に出せない文書の監査・処理用途。
検証結果と各モデルの所感は別リポジトリのvault（[[ローカルLLMモデル運用リファレンス]]）にまとまっている。ここにはコードと運用手順だけを置く。

## 構成

| パス | 内容 |
| --- | --- |
| `bench/` | 評価ハーネス本体（doceval/cmdeval/giteval/ctxeval）。設計・使い方は`bench/README.md`、実際の呼び出しコマンド集は`bench/INVOCATIONS.md` |
| `aider-local-llm.sh` | このMacでAiderをローカルモデルに向けて起動するラッパー |
| `dsh-settings.example.yaml` | dshの`~/.dsh/settings.yaml`雛形。Ornith(MTPLX)とOllama(Qwen3.6 MLX/GGUF、Gemma4)を両方登録し、`agent-default-model`で切替。同居制約のメモ付き |
| `semif-server.py` | SemIf（Jev型の判断専用モデル、MLX、Qwen3.5-4B 4bit）を常駐HTTP化。`/v1/systemone`（Jev/open-jev互換: choice/noul/score）と`/decide`。`semif/.venv/bin/python semif-server.py --port 8090`。`semif/`はSemIfのcheckout（別途clone、git管理外） |
| `serve-dsh-web.sh` / `tcp-proxy.py` | dsh Web UIをこのMacで起動し、Tailscale IPでスマホ/別PCから開けるようにする `start/stop/status`。dsh webは127.0.0.1にしかbindできないため、標準ライブラリだけのTCPプロキシをTailscale IPに置く。認証CookieがSameSite=StrictなのでURLはアドレスバーに貼って開く |
| `serve-ornith.sh` | Ornith-1.5(MTPLX)をLAN/Tailscale向けにホストする `start/stop/status`。起動前にOllamaのモデルを自動アンロード（同時ロード不可）。dsh/Aider/生API用、Claude Codeの対話セッションには使わない |
| `litellm-dwq-v2.yaml` | LiteLLM設定。`mlx_lm.server`（OpenAI Chat Completions限定）をClaude Code向けのAnthropic/Responses互換に変換するブリッジ |
| `backup_models.py` | モデルを外付けディスクへコピー（元ファイルは削除しない、SHA-256照合込み） |
| `remove_backed_up_ornith.py` / `remove_backed_up_qwen_mxfp4.py` | 退避・照合済みモデルのみを内蔵ディスクから削除するスクリプト（対象限定、他ファイルは触らない） |
| `ollama_footprint.py` / `ollama_rebench.py` | Ollamaのメモリ使用量・生成速度の計測 |
| `download_jundot.py` | 個別モデルのダウンロードスクリプト例 |
| `launchd/com.yoshiri.dsh-web*.plist` | dsh Web UI（127.0.0.1:3081）とTCPプロキシ（Tailscale IP:3080）を常駐化するLaunchAgentの雛形（`<TAILSCALE_IP>`/`<LAN_IP>`を置換して`~/Library/LaunchAgents/`へ）。作業ディレクトリは`~/dsh-workspace`、プロキシは`~/.local/bin/tcp-proxy.py`——launchd起動プロセスは`~/Documents`配下にTCCで触れないため外に置く。`serve-dsh-web.sh`はLaunchAgent導入済みなら`launchctl`経由で制御する |
| `com.yoshiri.ollama-host.plist` / `com.yoshiri.mlx-qwen-coder.plist` | launchd設定（`~/Library/LaunchAgents/`に実体を配置）。前者はOllamaの`OLLAMA_HOST`を設定 |

## サーバー

Ollamaは`OLLAMA_HOST=0.0.0.0:11434`で全インターフェースにbind（2026-09-21変更）。実際のLAN IP・Tailscale IPは環境ごとに異なるため、このリポジトリには含めていない。`OLLAMA_LAN_HOST`/`OLLAMA_TAILSCALE_HOST`のような環境変数に自分の値を入れて使う。

- ローカル: `http://127.0.0.1:11434`
- 自宅LAN: `http://${OLLAMA_LAN_HOST}:11434`（`ipconfig getifaddr en0`等で確認、変わったらplistを更新）
- Tailscale経由（外出先含む）: `http://${OLLAMA_TAILSCALE_HOST}:11434`（`tailscale status`でこのMacのIPを確認）

**設定変更時の注意:** `~/Library/LaunchAgents/com.yoshiri.ollama-host.plist`を編集した後は`launchctl bootout`→`bootstrap`で再読込し、さらに**Ollama.appを完全に終了・再起動**しないと新しい`OLLAMA_HOST`が反映されない（実行中の`ollama serve`は起動時点の値をキャッシュしているため、`launchctl setenv`を後から呼んでも効かない）。

推奨モデル: `qwen3.6:35b-a3b-q4_K_M-32k`（GGUF）または`qwen3.6:35b-mlx-32k`（MLX）。両者に優劣はほぼ無い（詳細はvault参照）。

Ollama APIは標準では認証なし。TailscaleのtailnetとLANは信頼できる前提で運用している。

## GPUロックの運用

複数セッション（Claude Code / Codex等）が同時にこのMacのGPUを使わないよう、`/private/tmp/llm-server.lock`を手動規約として使う。サーバー起動前に存在確認、起動後は`model=... owner=... started=...`を書き込み、停止後に自分の分だけ削除する。`bench/`配下のハーネスはこのファイルを作成・削除しない（存在確認のみ）。

## このMacで使う（Aider）

```sh
cd /path/to/project
/Users/yoshiri/Documents/local-llm/aider-local-llm.sh
```

単発依頼:

```sh
/Users/yoshiri/Documents/local-llm/aider-local-llm.sh app.py --message "このファイルのバグを直して"
```

## 別PCから使う（Aider）

```sh
export OLLAMA_API_BASE=http://${OLLAMA_TAILSCALE_HOST}:11434   # Tailscale経由。LAN内ならOLLAMA_LAN_HOST
aider --model ollama_chat/qwen3.6:35b-a3b-q4_K_M \
  --weak-model ollama_chat/qwen3.6:35b-a3b-q4_K_M \
  --editor-model ollama_chat/qwen3.6:35b-a3b-q4_K_M
```

接続確認（スマホのブラウザでも可、"Ollama is running"と表示されればOK）:

```sh
curl http://${OLLAMA_TAILSCALE_HOST}:11434/api/tags
```

## Claude Code から mlx_lm.server（DWQ v2）を使う

mlx_lm.server は OpenAI 互換のみなので、LiteLLM を Anthropic→OpenAI 変換プロキシとして挟む（2026-09-19 検証）。

```sh
# 1. モデルサーバー（カード推奨のサンプリング設定を明示。--temperatureを渡さないと既定0.0に落ちる）
mlx_lm.server --model <DWQ v2 snapshot> --host 127.0.0.1 --port 8081 --trust-remote-code --max-tokens 8192 \
  --temp 0.7 --top-p 0.8 --top-k 20
# 2. 変換プロキシ（uvx で隔離環境に入る。provider は hosted_vllm にしないと /v1/responses を叩いて 404 になる）
uvx --from 'litellm[proxy]' litellm --config /Users/yoshiri/Documents/local-llm/litellm-dwq-v2.yaml --port 4000 --host 127.0.0.1
# 3. Claude Code
ANTHROPIC_BASE_URL=http://127.0.0.1:4000 ANTHROPIC_AUTH_TOKEN=sk-local claude --model dwq-v2
```

## 評価ハーネス

文書処理・シェル調査・git操作・長期コンテクストの4軸でモデルを評価するハーネスが`bench/`にある。設計思想・タスク一覧は`bench/README.md`、実際に通った呼び出しコマンドとランタイムごとの落とし穴（サンプリング設定、thinkingの止め方、GPUメモリ上限）は`bench/INVOCATIONS.md`を参照。

```sh
cd bench/doceval && python3 run_doceval.py --build-vault /private/tmp/doceval-vault
# 以降は bench/INVOCATIONS.md の該当ランタイム節を参照
```

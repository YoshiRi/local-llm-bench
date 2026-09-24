"""Antigravity SDK の対話CLI（Claude Code 風）。ローカルモデル（Ollama）で動く。

  .venv-antigravity/bin/python ag-chat.py                 # カレントディレクトリをワークスペースにして対話
  .venv-antigravity/bin/python ag-chat.py --resume        # このディレクトリでの前回の会話を続ける
  .venv-antigravity/bin/python ag-chat.py --yolo          # ツール実行を毎回確認しない（使い捨て環境向け）
  .venv-antigravity/bin/python ag-chat.py --model qwen3.6:35b-mlx-32k   # 画像を扱う時など

  別PCから: このスクリプトとSDKを入れ、AG_BASE_URL=http://<MacのIP>:11434/v1 を指定する。
  または Mac に ssh して実行する（ターミナルなので Web UI の Cookie/URL 問題が無い）。

権限の既定は Claude Code の既定と同じ考え方: 読むだけのツール（ファイル閲覧・一覧・検索）は
黙って許可、ファイル作成・編集・シェル実行はその都度 y/n で確認する（SDKの safe_defaults）。

入力中のコマンド: exit / quit で終了、/id で会話IDを表示。
会話は ~/.ag-chat/<ワークスペースごと>/ に保存され、--resume で続きから再開できる。
"""
import argparse
import asyncio
import hashlib
import os
import sys
import time
from pathlib import Path

from google.antigravity import (Agent, AgentBehavior, BuiltinTools, CapabilitiesConfig,
                                LocalOpenAIAgentConfig, SystemInstructionSection,
                                TemplatedSystemInstructions)
from google.antigravity.hooks import policy
from google.antigravity.utils import interactive
from google.antigravity.utils.interactive import async_input

CLOUD_ONLY = [BuiltinTools.GENERATE_IMAGE, BuiltinTools.SEARCH_WEB, BuiltinTools.READ_URL_CONTENT,
              BuiltinTools.SCHEDULE, BuiltinTools.START_SUBAGENT]


class PolicyFixedConfig(LocalOpenAIAgentConfig):
    """google-antigravity 0.1.18 の LocalOpenAIAgentConfig.create_strategy は policies を
    接続に渡し忘れており、deny_all ですら無視されて全ツールが無確認で走る（2026-09-24確認）。
    Gemini用の LocalAgentConfig は渡している。生成後の strategy に差し込んで効かせる。"""

    def create_strategy(self, *, tool_runner, hook_runner):
        s = super().create_strategy(tool_runner=tool_runner, hook_runner=hook_runner)
        s._policies = list(self.policies)
        return s


def session_dir(ws: str) -> Path:
    d = Path.home() / ".ag-chat" / (Path(ws).name + "-" + hashlib.sha1(ws.encode()).hexdigest()[:8])
    d.mkdir(parents=True, exist_ok=True)
    return d


async def main(a) -> None:
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    ws = os.getcwd()
    sd = session_dir(ws)
    last = sd / "last_conversation_id"
    conv = last.read_text().strip() if a.resume and last.exists() else None
    if a.resume and not conv:
        print("(このディレクトリの保存済み会話が無いので新規で始めます)")

    cfg = PolicyFixedConfig(
        model=a.model,
        base_url=a.base_url,
        workspaces=[ws],
        save_dir=str(sd),
        # SDKの既定システムプロンプトは英語で、Ornithが中国語で返すことがあった。既定は残して1節だけ足す
        system_instructions=TemplatedSystemInstructions(sections=[SystemInstructionSection(
            title="language", content="Reply in the same language as the user's latest message "
                                      "(Japanese if the user writes Japanese).")]),
        conversation_id=conv,
        policies=[policy.allow_all()] if a.yolo else policy.safe_defaults(interactive.ask_user_handler),
        hooks=[interactive.AskQuestionHook()],
        capabilities=CapabilitiesConfig(enable_subagents=False, disabled_tools=CLOUD_ONLY,
                                        agent_behavior=AgentBehavior.INTERACTIVE),
    )
    print(f"ag-chat  model={a.model}  workspace={ws}")
    print(f"         {'ツール実行は確認なし (--yolo)' if a.yolo else '編集・シェル実行は毎回 y/n で確認'}"
          f"{'  / 会話を再開: ' + conv if conv else ''}")
    print("exit で終了、/id で会話ID\n")

    async with Agent(cfg) as agent:
        last.write_text(agent.conversation_id or "")
        while True:
            try:
                text = (await async_input("\n→ ")).strip()
            except (KeyboardInterrupt, EOFError, asyncio.CancelledError):
                break
            if not text:
                continue
            if text in ("exit", "quit", "/exit"):
                break
            if text == "/id":
                print(agent.conversation_id); continue
            if text == "/usage":
                u = agent.conversation.total_usage
                if u is None or u.prompt_token_count is None:
                    print("(このサーバーはトークン数を返さない。Ollama のOpenAI互換APIでは取れない)")
                else:
                    print(f"累計 prompt={u.prompt_token_count} output={u.candidates_token_count}")
                continue
            t = time.time()
            try:
                resp = await agent.chat(text)
                async for chunk in resp:
                    sys.stdout.write(chunk); sys.stdout.flush()
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\n(中断)"); continue
            u = resp.usage_metadata
            tok = f", prompt {u.prompt_token_count} / out {u.candidates_token_count} tok" if u and u.prompt_token_count else ""
            print(f"\n\033[2m[{time.time() - t:.1f}s{tok}]\033[0m")
            last.write_text(agent.conversation_id or "")
    print("\nbye")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=os.environ.get("AG_MODEL", "ornith-1.5:35b-a3b-mtp-32k"))
    ap.add_argument("--base-url", default=os.environ.get("AG_BASE_URL", "http://127.0.0.1:11434/v1"))
    ap.add_argument("--resume", action="store_true", help="このディレクトリでの前回の会話を続ける")
    ap.add_argument("--yolo", action="store_true", help="ツール実行を確認しない")
    asyncio.run(main(ap.parse_args()))

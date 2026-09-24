"""Google Antigravity SDK を `claude -p` 相当の単発CLIとして動かす（ベンチのハーネスから呼ぶ用）。

  .venv-antigravity/bin/python antigravity-run.py "<prompt>"
  AG_MODEL=qwen3.6:35b-mlx-32k .venv-antigravity/bin/python antigravity-run.py "<prompt>"
  AG_LITERT=~/.litert-lm/models/gemma4-26b/model.litertlm .venv-antigravity/bin/python antigravity-run.py "<prompt>"

カレントディレクトリをワークスペースにして、Ollama の OpenAI互換API（LocalOpenAIAgentConfig）で
ローカルモデルを使う。AG_LITERT に .litertlm のパスを渡すと、代わりにSDK公式のGemma経路
（LiteRTAgentConfig: SDKがLiteRT-LMのGPUバックエンドを自前で起動）を使う。ツール呼び出しは全許可（allow_all）——`claude -p --permission-mode
acceptEdits --allowedTools Bash,...` と同じ扱いで、使い捨てのサンドボックスで使う前提。
クラウド前提のツール（画像生成・Web検索・URL読込・スケジュール・サブエージェント）は外す。

  pip: uv venv --python 3.12 .venv-antigravity && uv pip install --python .venv-antigravity/bin/python google-antigravity
"""
import asyncio
import os
import sys
import time

from google.antigravity import Agent, BuiltinTools, CapabilitiesConfig, LiteRTAgentConfig, LocalOpenAIAgentConfig
from google.antigravity.hooks import policy

MODEL = os.environ.get("AG_MODEL", "ornith-1.5:35b-a3b-mtp-32k")
BASE_URL = os.environ.get("AG_BASE_URL", "http://127.0.0.1:11434/v1")


async def main(prompt: str) -> None:
    os.environ.setdefault("OPENAI_API_KEY", "ollama")
    common = dict(
        workspaces=[os.getcwd()],
        policies=[policy.allow_all()],
        capabilities=CapabilitiesConfig(
            enable_subagents=False,
            disabled_tools=[BuiltinTools.GENERATE_IMAGE, BuiltinTools.SEARCH_WEB,
                            BuiltinTools.READ_URL_CONTENT, BuiltinTools.SCHEDULE,
                            BuiltinTools.START_SUBAGENT, BuiltinTools.ASK_QUESTION],
        ),
    )
    litert = os.environ.get("AG_LITERT")
    if litert:
        cfg = LiteRTAgentConfig(model_path=os.path.expanduser(litert), **common)
    else:
        cfg = LocalOpenAIAgentConfig(model=MODEL, base_url=BASE_URL, **common)
    t = time.time()
    async with Agent(cfg) as agent:
        resp = await agent.chat(prompt)
        print(await resp.text())
    print(f"[antigravity-run] model={litert or MODEL} {time.time() - t:.1f}s", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))

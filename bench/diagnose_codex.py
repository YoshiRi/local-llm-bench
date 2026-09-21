"""CPU-only version startup diagnostics. Never changes installed binaries."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


def main():
    results = []
    binaries = ['/opt/homebrew/bin/codex',
                '/Applications/ChatGPT.app/Contents/Resources/codex']
    with tempfile.TemporaryDirectory(prefix='codex-diagnostic-') as home:
        for binary in binaries:
            for mode in ('baseline', 'rust_log', 'empty_home', 'network_denied'):
                env = dict(os.environ)
                command = [binary, '--version']
                if mode == 'rust_log':
                    env['RUST_LOG'] = 'trace'
                if mode in ('empty_home', 'network_denied'):
                    env['CODEX_HOME'] = home
                if mode == 'network_denied':
                    command = ['/usr/bin/sandbox-exec', '-p',
                               '(version 1)(allow default)(deny network*)'] + command
                start = time.monotonic()
                p = subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, start_new_session=True)
                timed_out = False
                try:
                    out, err = p.communicate(timeout=8)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(p.pid, signal.SIGKILL)
                    out, err = p.communicate()
                row = dict(binary=binary, mode=mode, seconds=time.monotonic()-start,
                           timeout=timed_out, exit=p.returncode,
                           stdout=out.decode(errors='replace'), stderr=err.decode(errors='replace'))
                results.append(row)
                print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()

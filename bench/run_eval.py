#!/usr/bin/env python3
"""Sequential local agent evaluation. --dry-run performs no writes or requests."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

PROMPT = ("Fix parse_duration() in duration_parser.py so that all tests in "
          "test_duration_parser.py pass. Preserve the public API, keep returning integer "
          "seconds, preserve TypeError for non-string input, and raise ValueError when "
          "the entire input is not a valid duration. Do not modify the tests. "
          "Run 'python3 -m unittest -v' to verify before finishing.")
DEFAULT_PROXY = Path('/Users/yoshiri/Documents/obsidean_note/attachments/'
                     'local-llm-bench-20260919/logproxy.py')


def now():
    return datetime.now(timezone.utc).isoformat()


def stop(p):
    if p is not None:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()


def capture(cmd, cwd=None, timeout=60, env=None):
    start = time.monotonic()
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    timed_out = False
    try:
        stdout, stderr = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop(p)
        stdout, stderr = p.communicate()
    except BaseException:
        stop(p)
        raise
    return dict(command=cmd, exit=p.returncode, stdout=stdout, stderr=stderr,
                real_seconds=time.monotonic()-start, timeout=timed_out)


class Lock:
    def __init__(self, path, model, wait):
        self.path, self.model, self.wait = path, model, wait
        self.identity = None

    def acquire(self):
        deadline = time.monotonic() + self.wait
        while True:
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('LLM lock exists; not starting a server or inference')
                time.sleep(min(2, max(0, deadline-time.monotonic())))
        with os.fdopen(fd, 'w') as f:
            self.identity = os.fstat(f.fileno()).st_ino
            json.dump(dict(model=self.model, pid=os.getpid(), started_at=now(),
                           pid_role='evaluation owner; server_pid added when managed'), f)

    def server_pid(self, pid):
        with self.path.open('r+') as f:
            if os.fstat(f.fileno()).st_ino != self.identity:
                raise RuntimeError('LLM lock ownership changed')
            d = json.load(f)
            d['owner_pid'] = os.getpid()
            d['server_pid'] = d['pid'] = pid
            d['pid_role'] = 'managed server'
            f.seek(0)
            json.dump(d, f)
            f.truncate()

    def release(self):
        if self.identity is not None and self.path.exists():
            if self.path.stat().st_ino == self.identity:
                self.path.unlink()


def api(base, path, body=None):
    req = urllib.request.Request(base.rstrip('/') + path,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def cli_command(a):
    base = 'http://127.0.0.1:%d' % a.proxy_port
    binary = a.cli_bin or a.cli
    env = {}
    if a.cli == 'codex':
        cmd = [binary, '-a', 'never', 'exec', '--ignore-user-config', '--ignore-rules',
               '-s', 'workspace-write', '--json']
        for feature in ('apps', 'plugins', 'multi_agent', 'goals', 'browser_use',
                        'computer_use', 'view_image'):
            cmd += ['--disable', feature]
        cmd += ['--enable', 'skip_host_skill_discovery', '-c', 'web_search="disabled"',
                '-c', 'model_provider="bench_local"', '-c',
                'model_providers.bench_local={name="Local benchmark",base_url="' + base +
                '/v1",wire_api="responses",request_max_retries=0,stream_max_retries=0}',
                '-m', a.model, PROMPT]
    elif a.cli == 'aider':
        model = ('ollama_chat/' if a.provider == 'ollama' else 'openai/') + a.model
        env = {'OLLAMA_API_BASE': base, 'OPENAI_API_BASE': base + '/v1',
               'OPENAI_API_KEY': 'local-unused'}
        cmd = [binary, '--no-check-update', '--analytics-disable', '--yes-always',
               '--no-auto-commits', '--no-show-model-warnings', '--model', model,
               '--edit-format', 'whole', '--map-tokens', '1024',
               'duration_parser.py', 'test_duration_parser.py', 'README.md', '--message', PROMPT]
    else:
        env = {'ANTHROPIC_BASE_URL': base, 'ANTHROPIC_AUTH_TOKEN': 'local-unused',
               'ANTHROPIC_API_KEY': '', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'}
        cmd = [binary, '-p', PROMPT, '--model', a.model, '--output-format', 'json',
               '--allowedTools', 'Read,Edit,Write,Bash']
    cmd += a.cli_arg
    return cmd, env


def log_marker(path):
    if not path or not path.exists():
        return None
    s = path.stat()
    return s.st_ino, s.st_size


def log_delta(path, marker):
    if not path or not path.exists() or marker is None:
        return None, 'log unavailable at trial start or end'
    s = path.stat()
    if s.st_ino != marker[0] or s.st_size < marker[1]:
        return None, 'log rotated/truncated; metrics unavailable'
    with path.open('rb') as f:
        f.seek(marker[1])
        return f.read().decode(errors='replace'), None


def metrics(text):
    if text is None:
        return dict(cache_hits=None, cache_misses=None, ollama_memory_peak_gib=None)
    peaks = [float(x) for x in re.findall(r'memory peak="([\d.]+) GiB"', text)]
    has_cache_events = bool(re.search(r'msg="cache (hit|miss)"', text))
    return dict(cache_hits=len(re.findall(r'msg="cache hit"', text)) if has_cache_events else None,
                cache_misses=len(re.findall(r'msg="cache miss"', text)) if has_cache_events else None,
                cache_matched=[int(x) for x in re.findall(r'cache hit"[^\n]*matched=(\d+)', text)],
                mlx_prompt_cache_sequences=[int(x) for x in re.findall(r'Prompt Cache: (\d+) sequences', text)],
                ollama_memory_peak_gib=max(peaks) if peaks else None)


def verify(repo, seed_commit):
    tests = capture(['python3', '-m', 'unittest', '-v'], repo)
    # Structured result distinguishes the expected ValueError from import/syntax failures.
    code = ("import json\nfrom duration_parser import parse_duration\n"
            "try:\n r=parse_duration('1 2h'); print(json.dumps({'result':r,'pass':False}))\n"
            "except ValueError as e:\n print(json.dumps({'exception':'ValueError','pass':True,'message':str(e)}))\n")
    probe = capture(['python3', '-c', code], repo)
    diff = capture(['git', 'diff', seed_commit, '--stat'], repo)
    test_diff = capture(['git', 'diff', seed_commit, '--', 'test_duration_parser.py'], repo)
    output = tests['stdout'] + tests['stderr']
    total = re.search(r'Ran (\d+) tests?', output)
    passed = len(re.findall(r'^test_.* \.\.\. ok$', output, re.M))
    return dict(unittest=tests, test_total=int(total[1]) if total else None,
                test_passed=passed, extra_probe=probe, diff_stat=diff,
                tests_unchanged=not test_diff['stdout'] and test_diff['exit'] == 0,
                status=capture(['git', 'status', '--short'], repo))


def wait_proxy(p, port):
    for _ in range(100):
        if p.poll() is not None:
            raise RuntimeError('proxy exited before readiness')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.1):
                return
        except OSError:
            time.sleep(.1)
    raise TimeoutError('proxy did not start')


def trial(a, folder):
    folder.mkdir(parents=True, exist_ok=False)
    result = dict(started_at=now(), cli=a.cli, provider=a.provider, model=a.model)
    lock = Lock(a.lock, a.model, a.lock_wait)
    server = proxy = None
    safe_release = True
    log_handles = []
    try:
        lock.acquire()
        capture_result = capture(['git', 'clone', str(a.seed), str(folder/'repo')])
        if capture_result['exit']:
            raise RuntimeError(capture_result['stderr'])
        repo = folder/'repo'
        seed_commit = capture(['git', 'rev-parse', 'HEAD'], repo)['stdout'].strip()
        result['seed_commit'] = seed_commit
        if seed_commit != a.seed_commit:
            raise RuntimeError('seed commit differs from requested baseline')
        marker = log_marker(a.server_log)
        if a.server_command:
            server_log = (folder/'server.log').open('w')
            log_handles.append(server_log)
            server = subprocess.Popen(shlex.split(a.server_command), stdout=server_log,
                                      stderr=subprocess.STDOUT, start_new_session=True)
            lock.server_pid(server.pid)
            time.sleep(a.startup_wait)
            if server.poll() is not None:
                raise RuntimeError('managed server exited at startup')
        elif a.provider == 'ollama':
            if api(a.upstream, '/api/ps').get('models'):
                raise RuntimeError('another model is loaded; refusing to unload or benchmark it')
        else:
            raise RuntimeError('non-Ollama provider requires --server-command for owned lifecycle')
        with socket.socket() as s:
            s.bind(('127.0.0.1', a.proxy_port))
        proxy_log = (folder/'proxy.log').open('w')
        log_handles.append(proxy_log)
        proxy = subprocess.Popen([sys.executable, str(a.proxy_script), a.upstream,
                                  str(a.proxy_port), str(folder/'requests')],
                                 stdout=proxy_log, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        wait_proxy(proxy, a.proxy_port)
        cmd, overrides = cli_command(a)
        result['environment_overrides'] = overrides
        safe_release = False
        result['cli_result'] = capture(cmd, repo, a.timeout, dict(os.environ, **overrides))
        safe_release = not result['cli_result']['timeout'] and result['cli_result']['exit'] == 0
        result['real_seconds'] = result['cli_result']['real_seconds']
        result.update(verify(repo, seed_commit))
    except Exception as e:
        result['error'] = str(e)
    finally:
        stop(proxy)
        if server is not None:
            stop(server)
            safe_release = True
        elif lock.identity is not None and not safe_release:
            result['cleanup_warning'] = 'CLI failed/interrupted; lock retained. Check runner before manual release.'
        elif lock.identity is not None and a.provider == 'ollama' and 'cli_result' in result:
            try:
                result['unload'] = api(a.upstream, '/api/generate', {'model': a.model, 'keep_alive': 0})
                if api(a.upstream, '/api/ps').get('models'):
                    raise RuntimeError('runner still listed after unload')
            except Exception as e:
                safe_release = False
                result['cleanup_warning'] = str(e)
        for handle in log_handles:
            handle.close()
        if server is not None:
            log_text, warning = (folder/'server.log').read_text(), None
        else:
            log_text, warning = log_delta(a.server_log, locals().get('marker'))
        result['metrics'] = metrics(log_text)
        result['metrics']['log_warning'] = warning
        result['metrics']['request_count'] = (len(list((folder/'requests').glob('*POST*.json')))
                                              if (folder/'requests').exists() else None)
        result['metrics']['cache_semantics'] = 'Ollama hit count; MLX sequence inventory is not a hit count'
        if log_text is not None:
            (folder/'server-window.log').write_text(log_text)
        if safe_release:
            lock.release()
        result['lock_retained'] = lock.identity is not None and a.lock.exists()
        result['finished_at'] = now()
        (folder/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cli', choices=['aider', 'claude', 'codex'], required=True)
    p.add_argument('--provider', choices=['ollama', 'mlx', 'openai-compatible', 'anthropic-compatible'], required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--trials', type=int, default=1)
    p.add_argument('--upstream', required=True, help='Base URL without /v1; proxy does not translate APIs')
    p.add_argument('--cli-bin')
    p.add_argument('--cli-arg', action='append', default=[])
    p.add_argument('--server-command', help='Owned foreground server argv, parsed with shlex; no shell operators')
    p.add_argument('--startup-wait', type=float, default=10)
    p.add_argument('--server-log', type=Path, default=Path.home()/'.ollama/logs/server.log')
    p.add_argument('--proxy-script', type=Path, default=DEFAULT_PROXY)
    p.add_argument('--proxy-port', type=int, default=9999)
    p.add_argument('--seed', type=Path, default=Path('/private/tmp/aider-quality-eval/seed'))
    p.add_argument('--seed-commit', default='9b6732ce81d4cc002d8a3f00b2c0b3b1bc386849')
    p.add_argument('--lock', type=Path, default=Path('/private/tmp/llm-server.lock'))
    p.add_argument('--lock-wait', type=float, default=3600)
    p.add_argument('--timeout', type=float, default=900)
    p.add_argument('--output', type=Path, default=Path('/private/tmp/local-cli-eval'))
    p.add_argument('--dry-run', action='store_true')
    return p


def main():
    a = parser().parse_args()
    if a.trials < 1 or a.timeout <= 0 or a.lock_wait < 0:
        raise SystemExit('trials and timeout must be positive; lock-wait must be nonnegative')
    cmd, env = cli_command(a)
    if a.dry_run:
        print(json.dumps(dict(dry_run=True, lock_exists=a.lock.exists(), lock=str(a.lock),
            trials=a.trials, cli_command=cmd, environment_overrides=env,
            server_command=a.server_command, upstream=a.upstream,
            steps=['wait for lock; acquire atomically with model/PID/time',
                   'clone seed; verify baseline commit', 'start owned server or verify Ollama idle',
                   'start logging proxy', 'time CLI', 'unittest -v', "parse_duration('1 2h')",
                   'git diff baseline --stat; check tests unchanged',
                   'stop proxy/server or unload own model',
                   'save per-trial JSON and one report.json; release lock only when safe'],
            warnings=['No commands, server starts, API requests, clones or lock writes performed.',
                      'Codex requires Responses; mlx_lm.server alone is incompatible.',
                      'Claude requires Anthropic-compatible upstream; raw mlx is incompatible.',
                      'Unavailable metrics are null, never fabricated zero.']), indent=2))
        return
    def interrupted(signum, frame):
        raise KeyboardInterrupt('signal %d' % signum)
    signal.signal(signal.SIGTERM, interrupted)
    run = a.output/(datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    results = []
    try:
        for i in range(a.trials):
            result = trial(a, run/('trial-%03d' % (i+1)))
            results.append(result)
            if result.get('lock_retained') or result.get('error'):
                break
    finally:
        run.mkdir(parents=True, exist_ok=True)
        (run/'report.json').write_text(json.dumps(dict(requested_trials=a.trials, trials=results),
                                                 ensure_ascii=False, indent=2))
    print(run/'report.json')


if __name__ == '__main__':
    main()

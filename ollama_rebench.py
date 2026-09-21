import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.request

BASE = os.environ.get('OLLAMA_BASE', 'http://127.0.0.1:11434')
ROOT = Path('/private/tmp/aider-quality-eval/ollama-rebench-20260919')
MODELS = ['qwen3.6:35b-mlx', 'qwen3.6:35b-a3b-q4_K_M']
PROMPT = ('Fix parse_duration() so that all tests pass. Preserve the public API, '
          'keep returning integer seconds, preserve TypeError for non-string input, '
          'and raise ValueError when the entire input is not a valid duration. '
          'Do not remove or weaken tests.')


def api(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data,
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.load(response)


def monitor(stop, samples):
    while not stop.is_set():
        sample = {'time': time.time()}
        try:
            sample['models'] = api('/api/ps')['models']
            rows = subprocess.check_output(
                ['ps', '-axo', 'pid=,rss=,command='], text=True).splitlines()
            sample['processes'] = []
            for row in rows:
                parts = row.strip().split(None, 2)
                if len(parts) == 3 and ('ollama runner' in parts[2]
                                      or 'ollama serve' in parts[2]
                                      or '/ollama ' in parts[2]
                                      or '/llama-server ' in parts[2]):
                    sample['processes'].append({'pid': int(parts[0]),
                                                'rss_bytes': int(parts[1]) * 1024,
                                                'command': parts[2]})
        except Exception as exc:
            sample['error'] = str(exc)
        samples.append(sample)
        stop.wait(1)


ROOT.mkdir(parents=True, exist_ok=False)
for model in MODELS:
    name = model.replace(':', '-')
    folder = ROOT / name
    subprocess.run(['git', 'clone', '/private/tmp/aider-quality-eval/seed', str(folder)], check=True)
    settings = folder / 'model-settings.yml'
    settings.write_text(json.dumps([{'name': 'ollama_chat/' + model,
                                    'extra_params': {'num_ctx': 16384,
                                                     'max_tokens': 8192,
                                                     'temperature': 0.0}}]))
    result = {'model': model, 'context_requested': 16384, 'max_output': 8192,
              'show': api('/api/show', {'model': model})}
    samples = []
    stop = threading.Event()
    watcher = threading.Thread(target=monitor, args=(stop, samples))
    watcher.start()
    try:
        print('START', model, flush=True)
        speed = []
        for trial in range(4):
            response = api('/api/generate', {
                'model': model, 'prompt': 'Write a detailed explanation of how a hash table works.',
                'stream': False, 'keep_alive': '15m',
                'options': {'num_ctx': 16384, 'num_predict': 256, 'temperature': 0.0}})
            response.pop('response', None)
            response.pop('thinking', None)
            response['generation_tps'] = response.get('eval_count', 0) / max(response.get('eval_duration', 0) / 1e9, 1e-9)
            response['trial'] = trial
            speed.append(response)
            print('SPEED', model, trial, response['generation_tps'], flush=True)
        result['speed'] = speed
        result['loaded_before_aider'] = api('/api/ps')
        result['aider_started_at'] = time.time()
        env = dict(os.environ, OLLAMA_API_BASE=BASE)
        command = ['/Users/yoshiri/.local/bin/aider', '--no-check-update', '--analytics-disable',
                   '--yes-always', '--no-show-model-warnings', '--model', 'ollama_chat/' + model,
                   '--model-settings-file', str(settings), '--edit-format', 'whole',
                   '--map-tokens', '1024', 'duration_parser.py', 'test_duration_parser.py', 'README.md',
                   '--message', PROMPT]
        with (folder / 'aider-output.log').open('w') as log:
            process = subprocess.Popen(command, cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                result['aider_exit'] = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                result['aider_timeout'] = True
        result['aider_seconds'] = time.time() - result['aider_started_at']
        result['aider_finished_at'] = time.time()
        tests = subprocess.run(['python3', '-m', 'unittest', '-v'], cwd=folder,
                               text=True, capture_output=True)
        result['test_exit'] = tests.returncode
        result['tests'] = tests.stdout + tests.stderr
        result['diff'] = subprocess.check_output(['git', 'diff', '9b6732c', '--',
            'duration_parser.py', 'test_duration_parser.py', 'README.md'], cwd=folder, text=True)
        result['commit'] = subprocess.check_output(['git', 'log', '-1', '--oneline'], cwd=folder, text=True)
        probe = subprocess.run(['python3', '-c',
            'from duration_parser import parse_duration; print(parse_duration("1 2h"))'],
            cwd=folder, text=True, capture_output=True)
        result['extra_probe'] = {'exit': probe.returncode, 'output': probe.stdout + probe.stderr}
        print('RESULT', model, result['aider_seconds'], result['test_exit'], flush=True)
    finally:
        stop.set()
        watcher.join()
        result['memory_samples'] = samples
        (folder / 'result.json').write_text(json.dumps(result, indent=2))
        api('/api/generate', {'model': model, 'keep_alive': 0})
        print('SAVED', str(folder / 'result.json'), flush=True)

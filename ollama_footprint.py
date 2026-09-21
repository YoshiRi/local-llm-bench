import json
from pathlib import Path
import subprocess
import time

root = Path('/private/tmp/aider-quality-eval/ollama-rebench-20260919')
saved = root / 'footprints.json'
records = json.loads(saved.read_text()) if saved.exists() else []
while True:
    rows = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True).splitlines()
    active = any('Python ' in row and '/local-llm/ollama_rebench.py' in row for row in rows)
    if not active:
        break
    for row in rows:
        if '/ollama runner ' not in row and '/llama-server ' not in row:
            continue
        pid = int(row.strip().split(None, 1)[0])
        result = subprocess.run(['vmmap', '-summary', str(pid)], text=True, capture_output=True, timeout=15)
        records.append({'time': time.time(), 'pid': pid, 'command': row.strip(),
                        'exit': result.returncode, 'output': result.stdout + result.stderr})
        (root / 'footprints.json').write_text(json.dumps(records, indent=2))
        print(pid, ' | '.join(line.strip() for line in result.stdout.splitlines()
                             if 'Physical footprint' in line), flush=True)
    time.sleep(20)

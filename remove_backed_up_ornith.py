"""Remove only the verified Ornith HF cache and its unshared global blobs."""
import json
from pathlib import Path
import shutil

hub = Path.home()/'.cache/huggingface/hub'
source = hub/'models--wang-yang--Ornith-1.5-35B-A3B-MTPLX-4bit'
backup = Path('/Volumes/ExtremeSSD/LocalLLM/backup-20260919-235029')
manifest = json.loads((backup/'checksums.json').read_text())
rows = [r for r in manifest['files'] if r['path'].startswith('MLX/wang-yang--Ornith-')]
assert manifest['verified'] and len(rows) == 18
for r in rows:
    assert (backup/r['path']).is_file()
    assert (backup/r['path']).stat().st_size == r['bytes']
    assert Path(r['source']).stat().st_size == r['bytes']
assert not Path('/private/tmp/llm-server.lock').exists(), 'LLM lock exists; aborting'
targets = {p.resolve() for p in source.rglob('*') if p.is_file()}
external = {p for p in targets if not p.is_relative_to(source)}
assert all(p.is_relative_to(hub/'blobs') for p in external)
used_elsewhere = set()
for model in hub.glob('models--*'):
    if model == source:
        continue
    for p in model.rglob('*'):
        if p.is_file() or p.is_symlink():
            if p.resolve() in external:
                used_elsewhere.add(p.resolve())
deletable = external - used_elsewhere
size = sum(p.stat().st_size for p in targets if p.is_relative_to(source) or p in deletable)
print(json.dumps({'unshared_blob_count': len(deletable), 'shared_blobs_preserved': len(used_elsewhere),
                  'removed_file_bytes': size}), flush=True)
shutil.rmtree(source)
for p in deletable:
    p.unlink()
print(json.dumps({'removed': str(source), 'backup_preserved': str(backup), 'complete': True}), flush=True)

"""Remove only backed-up OsaurusAI MXFP4; leave every Ollama file untouched."""
import hashlib
import json
from pathlib import Path
import shutil

home = Path.home()
hub = home/'.cache/huggingface/hub'
source = hub/'models--OsaurusAI--Qwen3.6-35B-A3B-mxfp4'
backup = Path('/Volumes/ExtremeSSD/LocalLLM/backup-20260919-235029')
ollama = home/'.ollama/models'


def ollama_inventory():
    files = {}
    for p in ollama.rglob('*'):
        if p.is_file():
            st = p.stat()
            files[str(p.relative_to(ollama))] = (st.st_ino, st.st_size, st.st_mtime_ns)
    manifests = {str(p.relative_to(ollama)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (ollama/'manifests').rglob('*') if p.is_file()}
    return files, manifests


before = ollama_inventory()
manifest = json.loads((backup/'checksums.json').read_text())
rows = [r for r in manifest['files'] if r['path'].startswith('MLX/OsaurusAI--Qwen3.6-35B-A3B-mxfp4/')]
assert manifest['verified'] and len(rows) == 16
assert {str(p) for p in (source/'snapshots').rglob('*') if p.is_file()} == {r['source'] for r in rows}
for r in rows:
    assert (backup/r['path']).is_file()
    assert (backup/r['path']).stat().st_size == Path(r['source']).stat().st_size == r['bytes']
assert not Path('/private/tmp/llm-server.lock').exists(), 'LLM lock exists; aborting'
targets = {p.resolve() for p in source.rglob('*') if p.is_file()}
external = {p for p in targets if not p.is_relative_to(source)}
assert all(p.is_relative_to(hub/'blobs') for p in external)
used_elsewhere = set()
for model in hub.glob('models--*'):
    if model == source:
        continue
    for p in model.rglob('*'):
        if (p.is_file() or p.is_symlink()) and p.resolve() in external:
            used_elsewhere.add(p.resolve())
deletable = external - used_elsewhere
size = sum(p.stat().st_size for p in targets if p.is_relative_to(source) or p in deletable)
shutil.rmtree(source)
for p in deletable:
    p.unlink()
after = ollama_inventory()
print(json.dumps(dict(removed=str(source), removed_file_bytes=size,
                      shared_blobs_preserved=len(used_elsewhere),
                      ollama_inventory_unchanged=before == after,
                      ollama_manifests=list(after[1]), backup_preserved=str(backup)), indent=2))
assert before == after, 'Ollama files changed externally during deletion; inspect before proceeding'

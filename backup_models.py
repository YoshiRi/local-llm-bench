"""Copy selected local models to an external volume; never remove sources."""
import hashlib
import json
from pathlib import Path
from datetime import datetime
import shutil


def main():
    home = Path.home()
    volume = Path('/Volumes/ExtremeSSD')
    if not volume.is_mount():
        raise RuntimeError('External volume is not mounted')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    root = volume/'LocalLLM'
    stage = root/('.partial-' + stamp)
    final = root/('backup-' + stamp)
    hub = home/'.cache/huggingface/hub'
    selected = [
        ('wang-yang--Ornith-1.5-35B-A3B-MTPLX-4bit', '44d09b73035cb12dcb474c3c0d1c8629acdcf5ba'),
        ('OsaurusAI--Qwen3.6-35B-A3B-mxfp4', '5a6aaf3d0db3590f186d743b99c9b9d270ec7857'),
    ]
    jobs = []
    manifests = {}
    for model, revision in selected:
        source = hub/('models--' + model)/'snapshots'/revision
        for p in sorted(source.rglob('*')):
            if p.is_file():
                jobs.append((p, Path('MLX')/model/revision/p.relative_to(source), None))
    ollama = home/'.ollama/models'
    refs = set()
    for p in sorted((ollama/'manifests').rglob('*')):
        if p.is_file():
            raw = p.read_bytes()
            manifests[str(p)] = raw
            d = json.loads(raw)
            refs.update(x['digest'] for x in [d['config']] + d['layers'])
            jobs.append((p, Path('Ollama/models')/p.relative_to(ollama), hashlib.sha256(raw).hexdigest()))
    for digest in sorted(refs):
        algo, value = digest.split(':', 1)
        if algo != 'sha256' or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Invalid Ollama digest: ' + digest)
        p = ollama/'blobs'/('sha256-' + value)
        jobs.append((p, Path('Ollama/models/blobs')/p.name, value))
    for p in sorted((ollama/'metadata').rglob('*')):
        if p.is_file():
            jobs.append((p, Path('Ollama/models')/p.relative_to(ollama), None))
    total = sum(p.stat().st_size for p, _, _ in jobs)
    if shutil.disk_usage(volume).free < total + 1024**3:
        raise RuntimeError('Insufficient external disk space')
    stage.mkdir(parents=True, exist_ok=False)
    print(json.dumps(dict(stage=str(stage), final=str(final), files=len(jobs), bytes=total)), flush=True)
    records = []
    copied = 0
    for i, (src, rel, expected) in enumerate(jobs, 1):
        before = src.stat()
        dst = stage/rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        with src.open('rb') as reader, dst.open('xb') as writer:
            while True:
                data = reader.read(8*1024*1024)
                if not data:
                    break
                writer.write(data)
                h.update(data)
        after = src.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise RuntimeError('Source changed during copy: ' + str(src))
        digest = h.hexdigest()
        if expected and digest != expected:
            raise RuntimeError('Source digest mismatch: ' + str(src))
        check = hashlib.sha256()
        with dst.open('rb') as reader:
            while True:
                data = reader.read(8*1024*1024)
                if not data:
                    break
                check.update(data)
        if check.hexdigest() != digest or dst.stat().st_size != before.st_size:
            raise RuntimeError('Destination verification failed: ' + str(dst))
        records.append(dict(path=str(rel), bytes=before.st_size, sha256=digest, source=str(src)))
        copied += before.st_size
        if i % 50 == 0 or before.st_size > 1024**3 or i == len(jobs):
            print(json.dumps(dict(verified_files=i, total_files=len(jobs), verified_GB=round(copied/1e9, 3), total_GB=round(total/1e9, 3))), flush=True)
    current = {str(p): p.read_bytes() for p in (ollama/'manifests').rglob('*') if p.is_file()}
    if current != manifests:
        raise RuntimeError('Ollama manifest set changed during backup; keep partial backup for inspection')
    (stage/'checksums.json').write_text(json.dumps(dict(created_at=stamp, verified=True, files=records), indent=2))
    (stage/'README.txt').write_text(
        'Local LLM model backup\n\n'
        'All files were copied and independently read back with SHA-256 verification.\n'
        'Sources on the Mac were NOT removed. No model server was started or stopped.\n\n'
        'MLX/: standalone snapshot directories; symlinks were resolved into real files.\n'
        'Point mlx_lm at the revision directory containing config.json, or copy it\n'
        'back to an internal disk first. Ornith MTPLX weights are included, not the runtime.\n\n'
        'Ollama/models/: manifests, all referenced shared blobs, and metadata.\n'
        'To restore, stop Ollama and coordinate the GPU lock first, then copy these\n'
        'directories into the intended Ollama models directory. Do not overwrite\n'
        'newer manifests blindly. Alternatively configure OLLAMA_MODELS to a restored\n'
        'models directory before launching Ollama. Compatible Ollama MLX support\n'
        'is required for the MLX tags. This backup does not include the Ollama app.\n\n'
        'checksums.json records relative paths, sizes and hashes.\n'
        'This exFAT backup contains ordinary files, not HF cache symlinks.\n')
    stage.rename(final)
    print(json.dumps(dict(complete=True, path=str(final), files=len(records), bytes=total)), flush=True)


if __name__ == '__main__':
    main()

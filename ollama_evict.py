#!/usr/bin/env python3
"""Ollamaのタグを内蔵ディスクから外す。外付けSSDにblob・manifestが揃っていることをSHA-256で確認してから `ollama rm` する。
足りないファイルは先にコピーする。外付けが無ければ何もしない。

  python3 ollama_evict.py gemma4:26b-a4b-it-mtp-q4_K_M [tag ...]
  python3 ollama_evict.py --dry-run <tag>

共有blob（例: -32k タグと元タグ）は、他のタグが参照している限り `ollama rm` が消さないので気にしなくてよい。
"""
import hashlib, json, shutil, subprocess, sys
from pathlib import Path

HOME = Path.home()
SRC = HOME / '.ollama/models'
VOLUME = Path('/Volumes/ExtremeSSD')
DST = VOLUME / 'LocalLLM/backup-20260919-235029/Ollama/models'
LIB = 'manifests/registry.ollama.ai/library'


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 24), b''):
            h.update(b)
    return h.hexdigest()


def manifest_path(root: Path, tag: str) -> Path:
    name, _, ver = tag.partition(':')
    return root / LIB / name / (ver or 'latest')


def digests(manifest: Path):
    d = json.loads(manifest.read_bytes())
    return [x['digest'] for x in [d['config']] + d['layers']]


def loaded_models():
    out = subprocess.run(['ollama', 'ps'], capture_output=True, text=True).stdout.splitlines()
    return [l.split()[0] for l in out[1:] if l.strip()]


def evict(tag: str, dry: bool) -> None:
    m = manifest_path(SRC, tag)
    if not m.is_file():
        print(f'{tag}: not installed locally'); return
    if tag in loaded_models():
        print(f'{tag}: currently loaded, unload it first (keep_alive 0)'); return
    for dg in digests(m):
        name = dg.replace(':', '-'); s = SRC / 'blobs' / name; f = DST / 'blobs' / name
        if f.exists() and f.stat().st_size == s.stat().st_size:
            continue
        print(f'{tag}: copying {name[:19]} ({s.stat().st_size / 1e9:.1f} GB) to SSD')
        if dry: continue
        shutil.copyfile(s, f)
        if sha256(f) != dg.split(':', 1)[1]:
            f.unlink(); raise SystemExit(f'{tag}: SHA-256 mismatch after copy: {name}')
    dm = manifest_path(DST, tag)
    if not (dm.exists() and dm.read_bytes() == m.read_bytes()):
        print(f'{tag}: copying manifest')
        if not dry:
            dm.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(m, dm)
    print(f'{tag}: SSD copy complete -> ollama rm')
    if not dry:
        subprocess.run(['ollama', 'rm', tag], check=True)


def main(argv):
    dry = '--dry-run' in argv
    tags = [a for a in argv if not a.startswith('--')]
    if not tags:
        raise SystemExit(__doc__)
    if not VOLUME.is_mount():
        raise SystemExit('ExtremeSSD is not mounted; nothing done')
    for t in tags:
        evict(t, dry)


if __name__ == '__main__':
    main(sys.argv[1:])

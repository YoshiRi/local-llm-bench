#!/usr/bin/env python3
"""外付けSSDに退避したOllamaのタグを内蔵ディスクへ戻す（再DL不要）。blobはSHA-256で照合してからコピーする。
外付けが無ければ何もしない。Ollamaの再起動は不要（次の `ollama list` から見える）。

  python3 ollama_restore.py gemma4:26b-a4b-it-mtp-q4_K_M [tag ...]
  python3 ollama_restore.py --list          # SSDにあるタグを表示
"""
import hashlib, json, shutil, sys
from pathlib import Path

HOME = Path.home()
DST = HOME / '.ollama/models'
VOLUME = Path('/Volumes/ExtremeSSD')
SRC = VOLUME / 'LocalLLM/backup-20260919-235029/Ollama/models'
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


def restore(tag: str) -> None:
    m = manifest_path(SRC, tag)
    if not m.is_file():
        print(f'{tag}: not on SSD'); return
    d = json.loads(m.read_bytes())
    free = shutil.disk_usage(HOME).free
    need = sum(x['size'] for x in [d['config']] + d['layers']
               if not (DST / 'blobs' / x['digest'].replace(':', '-')).exists())
    if need > free - 5e9:
        raise SystemExit(f'{tag}: need {need / 1e9:.1f} GB, only {free / 1e9:.1f} GB free (keeping 5 GB margin)')
    for x in [d['config']] + d['layers']:
        name = x['digest'].replace(':', '-'); s = SRC / 'blobs' / name; f = DST / 'blobs' / name
        if f.exists() and f.stat().st_size == x['size']:
            continue
        print(f'{tag}: copying {name[:19]} ({x["size"] / 1e9:.1f} GB) from SSD')
        tmp = f.with_suffix('.partial'); shutil.copyfile(s, tmp)
        if sha256(tmp) != x['digest'].split(':', 1)[1]:
            tmp.unlink(); raise SystemExit(f'{tag}: SHA-256 mismatch: {name}')
        tmp.rename(f)
    dm = manifest_path(DST, tag); dm.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(m, dm)
    print(f'{tag}: restored')


def main(argv):
    if not VOLUME.is_mount():
        raise SystemExit('ExtremeSSD is not mounted; nothing done')
    if '--list' in argv or not argv:
        for p in sorted((SRC / LIB).glob('*/*')):
            if p.name.startswith('._'):  # exFAT の AppleDouble ファイル
                continue
            print(f'{p.parent.name}:{p.name}')
        return
    for t in argv:
        restore(t)


if __name__ == '__main__':
    main(sys.argv[1:])

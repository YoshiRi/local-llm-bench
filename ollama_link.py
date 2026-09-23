#!/usr/bin/env python3
"""Ollamaのタグを「消さずに内蔵ディスクから外す」。blobの実体をSSDに置き、内蔵にはシンボリックリンクだけ残す。

  python3 ollama_link.py qwen3.6:35b-mlx-32k [tag ...]   # SSDへ退避してリンク化（`ollama list` に残る）
  python3 ollama_link.py --restore <tag> [...]           # 実体を内蔵に戻す（速度が要る常用モデル用）
  python3 ollama_link.py --status                        # 各タグが内蔵実体かSSDリンクかを表示

なぜこの形か: Ollamaの `OLLAMA_MODELS` は単一ディレクトリしか見ないので、内蔵とSSDを同時に
選択可能にはできない。一方 manifest は数KBなので内蔵に残し、GB級のblobだけSSD上の実体への
symlinkにすれば、全タグが `ollama list` に出たまま内蔵容量を使わない。読み出しはOSがリンクを
辿るのでOllama側の対応は不要。`ollama rm` してもリンクが消えるだけでSSDの実体は残る。

制約:
- **Ollamaサーバーに外付けボリュームへのアクセス許可が要る（2026-09-23に踏んだ）。** 許可が無いと
  Ollamaがリンク先を open() した所でブロックし、`ollama list` / `/api/tags` まで無応答になる
  （一覧は各タグの設定blobを読むため、ロードしないタグでも詰まる）。サーバー再起動では直らない。
  システム設定 > プライバシーとセキュリティ > ファイルとフォルダ（またはフルディスクアクセス）で
  Ollama に「リムーバブルボリューム」を許可してからリンク化すること。
- SSD(ExFAT)はsymlink不可なので、リンクは必ず内蔵(APFS)側に置く。SSD未マウント時はリンク先を
  失い、そのタグのロードだけが失敗する（他は無事）。
- ロードはUSB経由になるので冷間ロードが内蔵より遅い。常用モデルは --restore で内蔵に戻す。
- 複数タグが共有するblobは、リンク化対象に入っていないタグからも参照されている場合は実体のまま残す。
"""
import hashlib, json, os, shutil, subprocess, sys
from pathlib import Path

SRC = Path.home() / '.ollama/models'
VOLUME = Path('/Volumes/ExtremeSSD')
DST = VOLUME / 'LocalLLM/backup-20260919-235029/Ollama/models'
REG = 'manifests/registry.ollama.ai'


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 24), b''):
            h.update(b)
    return h.hexdigest()


def manifest_path(root: Path, tag: str) -> Path:
    """'qwen3.6:35b-mlx' も 'bvassie/ornith-1.5:35b-a3b-mtp' も解決する。"""
    name, _, ver = tag.partition(':')
    parts = name.split('/')
    if len(parts) == 1:
        parts = ['library'] + parts
    return root.joinpath(REG, *parts, ver or 'latest')


def digests(manifest: Path):
    d = json.loads(manifest.read_bytes())
    return [x['digest'] for x in [d['config']] + d['layers']]


def all_tags(root: Path):
    base = root / REG
    return ['/'.join(p.relative_to(base).parts[:-1]).replace('library/', '') + ':' + p.name
            for p in base.rglob('*') if p.is_file()] if base.is_dir() else []


def loaded_models():
    out = subprocess.run(['ollama', 'ps'], capture_output=True, text=True).stdout.splitlines()
    return [l.split()[0] for l in out[1:] if l.strip()]


def ensure_on_ssd(tag: str, m: Path) -> None:
    for dg in digests(m):
        name = dg.replace(':', '-')
        s, f = SRC / 'blobs' / name, DST / 'blobs' / name
        if f.is_file() and (not s.is_file() or f.stat().st_size == s.stat().st_size):
            continue
        if not s.is_file():
            raise SystemExit(f'{tag}: 内蔵にもSSDにもblobが無い: {name}')
        print(f'{tag}: copying {name[:19]} ({s.stat().st_size / 1e9:.1f} GB) to SSD')
        f.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, f)
        if sha256(f) != dg.split(':', 1)[1]:
            f.unlink()
            raise SystemExit(f'{tag}: SHA-256 mismatch after copy: {name}')
    dm = manifest_path(DST, tag)
    if not (dm.exists() and dm.read_bytes() == m.read_bytes()):
        dm.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(m, dm)


def link(tags) -> None:
    keep = set()   # リンク化しないタグが参照するblob = 実体のまま残す
    for t in all_tags(SRC):
        if t in tags:
            continue
        mp = manifest_path(SRC, t)
        if mp.is_file():
            keep.update(digests(mp))
    for tag in tags:
        m = manifest_path(SRC, tag)
        if not m.is_file():
            # 内蔵に無くSSDにだけ在るタグ（過去に ollama rm したもの）はmanifestだけ戻して
            # リンクを張る＝データ転送ゼロで `ollama list` に復活させる。
            sm = manifest_path(DST, tag)
            if not sm.is_file():
                print(f'{tag}: 内蔵にもSSDにも無い'); continue
            m.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(sm, m)
            print(f'{tag}: SSDのmanifestから復活')
        if tag in loaded_models():
            print(f'{tag}: currently loaded, unload it first'); continue
        ensure_on_ssd(tag, m)
        freed = 0
        for dg in digests(m):
            name = dg.replace(':', '-')
            s = SRC / 'blobs' / name
            if s.is_symlink() or dg in keep:
                continue
            size = s.stat().st_size if s.is_file() else 0
            tmp = s.with_name(name + '.linking')
            os.symlink(DST / 'blobs' / name, tmp)
            os.replace(tmp, s)
            freed += size
        print(f'{tag}: linked to SSD (内蔵から {freed / 1e9:.1f} GB 解放、`ollama list` には残る)')


def restore(tags) -> None:
    for tag in tags:
        m = manifest_path(SRC, tag)
        if not m.is_file():
            sm = manifest_path(DST, tag)
            if not sm.is_file():
                print(f'{tag}: SSDにも無い'); continue
            m.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(sm, m)
        used = 0
        for dg in digests(m):
            name = dg.replace(':', '-')
            s = SRC / 'blobs' / name
            if s.exists() and not s.is_symlink():
                continue
            f = DST / 'blobs' / name
            if not f.is_file():
                raise SystemExit(f'{tag}: SSDにblobが無い: {name}')
            print(f'{tag}: restoring {name[:19]} ({f.stat().st_size / 1e9:.1f} GB)')
            tmp = s.with_name(name + '.restoring')
            shutil.copyfile(f, tmp)
            if sha256(tmp) != dg.split(':', 1)[1]:
                tmp.unlink(); raise SystemExit(f'{tag}: SHA-256 mismatch after copy: {name}')
            os.replace(tmp, s)
            used += f.stat().st_size
        print(f'{tag}: 内蔵に実体を復元（{used / 1e9:.1f} GB）')


def status() -> None:
    print(f'{"TAG":44} {"内蔵実体":>9} {"SSDリンク":>10}')
    for t in sorted(all_tags(SRC)):
        mp = manifest_path(SRC, t)
        real = linked = 0
        for dg in digests(mp):
            s = SRC / 'blobs' / dg.replace(':', '-')
            if s.is_symlink():
                linked += s.stat().st_size if s.exists() else 0
            elif s.exists():
                real += s.stat().st_size
        print(f'{t:44} {real / 1e9:8.1f}G {linked / 1e9:9.1f}G')


def main(argv):
    if not VOLUME.is_mount():
        raise SystemExit('ExtremeSSD is not mounted; nothing done')
    tags = [a for a in argv if not a.startswith('--')]
    if '--status' in argv:
        status()
    elif '--restore' in argv:
        restore(tags)
    elif tags:
        link(tags)
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])

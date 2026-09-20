#!/usr/bin/env python3
from __future__ import annotations
import argparse, time
from pathlib import Path

DEFAULT_CACHE = Path.home() / '.cache' / 'orienteering-map-prep'

def prune(cache_root: Path, days: int = 10, dry_run: bool = False):
    root = cache_root.resolve()
    if not root.exists():
        return {'deleted_files': 0, 'deleted_dirs': 0, 'bytes_freed': 0}
    cutoff = time.time() - days * 86400
    deleted_files = deleted_dirs = bytes_freed = 0
    for p in sorted(root.rglob('*'), key=lambda x: len(x.parts), reverse=True):
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                size = p.stat().st_size
                if not dry_run:
                    p.unlink()
                deleted_files += 1
                bytes_freed += size
        except FileNotFoundError:
            pass
    for p in sorted([x for x in root.rglob('*') if x.is_dir()], key=lambda x: len(x.parts), reverse=True):
        try:
            if not any(p.iterdir()):
                if not dry_run:
                    p.rmdir()
                deleted_dirs += 1
        except (FileNotFoundError, OSError):
            pass
    return {'deleted_files': deleted_files, 'deleted_dirs': deleted_dirs, 'bytes_freed': bytes_freed}

def main():
    ap = argparse.ArgumentParser(description='Prune orienteering GIS cache files older than N days')
    ap.add_argument('--cache-root', type=Path, default=DEFAULT_CACHE)
    ap.add_argument('--days', type=int, default=10)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()
    res = prune(args.cache_root, args.days, args.dry_run)
    if args.verbose or args.dry_run:
        print(res)

if __name__ == '__main__':
    main()

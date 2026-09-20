from __future__ import annotations
import hashlib, os, re, shutil, subprocess, json
from pathlib import Path

SAFE_RE = re.compile(r'[^A-Za-z0-9._-]+')

def safe_name(text: str, default='project') -> str:
    s = SAFE_RE.sub('-', text.strip())[:80].strip('-._')
    return s or default

def run(cmd, *, cwd=None, env=None, check=True, capture=True):
    res = subprocess.run(cmd, cwd=cwd, env=env, text=True,
                         stdout=subprocess.PIPE if capture else None,
                         stderr=subprocess.PIPE if capture else None)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed ({res.returncode}): {' '.join(map(str, cmd))}\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
    return res

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    return path

def disk_free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free

def write_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

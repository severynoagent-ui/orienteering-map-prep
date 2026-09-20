from __future__ import annotations
import sys, time

class Logger:
    def __init__(self, path=None):
        self.path = path
        self._fh = open(path, 'a', encoding='utf-8') if path else None
    def log(self, msg: str):
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line, flush=True)
        if self._fh:
            self._fh.write(line + "\n"); self._fh.flush()
    def close(self):
        if self._fh: self._fh.close()

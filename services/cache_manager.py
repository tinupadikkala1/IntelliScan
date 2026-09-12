"""Cache manager.

A simple two-tier cache (in-memory + disk) with TTL and size-based eviction.
Used for expensive results such as generated thumbnails so they are not
recomputed on every selection.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import threading
import time
from typing import Any


class CacheManager:
    def __init__(
        self,
        cache_dir: str = "cache",
        ttl: int = 3600,
        max_entries: int = 1000,
    ) -> None:
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.ttl = ttl
        self.max_entries = max_entries
        self._mem: dict[str, tuple[bytes, float | None]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def _hash(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def get(self, key: str) -> bytes | None:
        h = self._hash(key)
        with self._lock:
            if h in self._mem:
                value, exp = self._mem[h]
                if exp is not None and time.time() > exp:
                    self._mem.pop(h, None)
                    return None
                return value
        # Memory miss -> try disk.
        path = os.path.join(self.cache_dir, h + ".cache")
        if os.path.exists(path):
            try:
                with open(path, "rb") as fh:
                    return fh.read()
            except OSError:
                return None
        return None

    def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        h = self._hash(key)
        exp = (ttl if ttl is not None else self.ttl)
        exp_ts = time.time() + exp if exp else None
        with self._lock:
            self._mem[h] = (value, exp_ts)
        path = os.path.join(self.cache_dir, h + ".cache")
        try:
            with open(path, "wb") as fh:
                fh.write(value)
        except OSError:
            pass
        self._evict()

    # ------------------------------------------------------------------ #
    # Structured data support (pickle-based)
    # ------------------------------------------------------------------ #
    def get_object(self, key: str) -> Any | None:
        """Retrieve a pickled Python object from cache."""
        data = self.get(key)
        if data is None:
            return None
        try:
            return pickle.loads(data)
        except Exception:
            return None

    def set_object(self, key: str, obj: Any, ttl: int | None = None) -> None:
        """Store a Python object in cache via pickle."""
        try:
            data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            return
        self.set(key, data, ttl)

    # ------------------------------------------------------------------ #
    def _evict(self) -> None:
        with self._lock:
            if len(self._mem) > self.max_entries:
                overflow = list(self._mem.keys())[self.max_entries:]
                for k in overflow:
                    self._mem.pop(k, None)
                    try:
                        os.remove(os.path.join(self.cache_dir, k + ".cache"))
                    except OSError:
                        pass
        try:
            files = []
            for f in os.listdir(self.cache_dir):
                if f.endswith(".cache"):
                    path = os.path.join(self.cache_dir, f)
                    try:
                        if os.path.exists(path):
                            files.append((f, os.path.getmtime(path)))
                    except OSError:
                        pass
            files.sort(key=lambda x: x[1])
            with self._lock:
                remaining_keys = set(self._mem.keys())
                i = 0
                while i < len(files):
                    fname, _ = files[i]
                    fhash = fname[:-6]
                    if fhash not in remaining_keys:
                        try:
                            os.remove(os.path.join(self.cache_dir, fname))
                            files.pop(i)
                            continue
                        except OSError:
                            pass
                    i += 1
            while len(files) > self.max_entries:
                fname, _ = files.pop(0)
                try:
                    os.remove(os.path.join(self.cache_dir, fname))
                except OSError:
                    pass
        except OSError:
            pass

    def clear(self) -> None:
        with self._lock:
            self._mem.clear()
        for name in os.listdir(self.cache_dir):
            try:
                os.remove(os.path.join(self.cache_dir, name))
            except OSError:
                pass

    def set_budget_mb(self, mb: int) -> None:
        """Map cache_size_mb to max_entries (avg entry ~256KB) + evict."""
        try:
            self.max_entries = max(64, int(mb or 0) * 4)
        except Exception:
            self.max_entries = 1024
        try:
            self._evict()
        except Exception:
            pass

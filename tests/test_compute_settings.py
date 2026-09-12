"""Compute settings wiring — every Performance option must affect backend."""

from services.compute import (
    apply_compute_settings,
    effective_embed_batch,
    effective_snapshot,
    ollama_options,
    resolve_threads,
    should_use_llm_rerank,
)


class _Cfg:
    def __init__(self, d):
        self._d = d

    def get(self, k, default=None):
        return self._d.get(k, default)


def test_resolve_threads_auto_and_cap():
    import os

    n = os.cpu_count() or 4
    assert resolve_threads(0) == n
    assert resolve_threads(9999) == n
    assert resolve_threads(2) == min(2, n)


def test_snapshot_defaults():
    s = effective_snapshot(_Cfg({}))
    assert s["embed_batch"] == 32
    assert s["gpu_enabled"] is True
    assert s["low_resource"] is False


def test_embed_batch_halved_in_low_resource():
    normal = effective_embed_batch(_Cfg({"compute.embed_batch": 32}))
    low = effective_embed_batch(_Cfg({"compute.embed_batch": 32, "compute.low_resource_mode": True}))
    assert low == max(8, normal // 2)
    assert not should_use_llm_rerank(_Cfg({"compute.low_resource_mode": True}))
    assert should_use_llm_rerank(_Cfg({}))


def test_ollama_options_gpu_off_forces_cpu():
    o = ollama_options(_Cfg({"compute.cpu_threads": 2, "compute.gpu_enabled": False}))
    assert o["num_thread"] == 2
    assert o["num_gpu"] == 0
    o2 = ollama_options(_Cfg({"compute.cpu_threads": 0, "compute.gpu_enabled": True}))
    assert "num_thread" in o2 and "num_gpu" not in o2


def test_apply_pool_and_cache():
    from PySide6.QtCore import QThreadPool

    from services.cache_manager import CacheManager

    pool = QThreadPool()
    import tempfile

    cm = CacheManager(cache_dir=tempfile.mkdtemp(), max_entries=10)
    snap = apply_compute_settings(
        _Cfg({"performance.max_threads": 7, "performance.cache_size_mb": 64}),
        pool=pool,
        cache=cm,
    )
    assert pool.maxThreadCount() == 7
    assert cm.max_entries == 256
    assert snap["max_threads"] == 7

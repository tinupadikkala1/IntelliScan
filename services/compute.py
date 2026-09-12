"""Compute device detection — CPU cores / GPU / iGPU (modern backend port).

Ported from New Folder `hardware/detector.py` + `utils/cpu_utils.py`.
Linux + Windows safe: every probe is guarded, never raises.
Used by Settings Compute section to tune indexing threads, batch sizes,
and STT/vision backends to available hardware.
"""

from __future__ import annotations

import logging
import os
import platform

logger = logging.getLogger(__name__)


def cpu_count() -> int:
    try:
        return os.cpu_count() or 4
    except Exception:
        return 4


def detect_devices() -> dict:
    """Return hardware summary: cpu, ram, cuda, onnx providers, igpu hints."""
    info: dict = {
        "platform": platform.system(),
        "cpu_count": cpu_count(),
        "torch_threads": None,
        "cuda": False,
        "onnx_providers": [],
        "dri": False,
        "directml": False,
        "openvino": False,
        "ollama_reachable": False,
    }
    # torch
    try:
        import torch

        info["torch_threads"] = torch.get_num_threads()
        try:
            info["cuda"] = bool(torch.cuda.is_available())
        except Exception:
            pass
    except Exception:
        pass
    # onnxruntime providers (CPU always, CUDA/DML/OpenVINO if installed)
    try:
        import onnxruntime

        info["onnx_providers"] = list(onnxruntime.get_available_providers())
    except Exception:
        pass
    # Linux iGPU hint
    try:
        info["dri"] = os.path.exists("/dev/dri")
    except Exception:
        pass
    # Windows DirectML / Intel OpenVINO (optional deps)
    try:
        import torch_directml  # noqa: F401

        info["directml"] = True
    except Exception:
        pass
    try:
        import openvino  # noqa: F401

        info["openvino"] = True
    except Exception:
        pass
    # Ollama reachable?
    try:
        import requests

        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        info["ollama_reachable"] = r.status_code == 200
    except Exception:
        pass
    return info


def resolve_threads(config_threads: int = 0) -> int:
    """Resolve configured cpu_threads (0=auto) to a concrete count."""
    try:
        v = int(config_threads or 0)
    except Exception:
        v = 0
    if v <= 0:
        return cpu_count()
    return max(1, min(v, cpu_count()))


def inference_options(settings_getter=None, num_thread: int = 0) -> dict:
    """Build Ollama options dict respecting cpu_threads.

    `settings_getter` is an optional callable like `config.get`.
    """
    threads = resolve_threads(num_thread)
    if settings_getter is not None:
        try:
            v = settings_getter("compute.cpu_threads", 0)
            threads = resolve_threads(int(v or 0))
        except Exception:
            pass
    # Ollama /api/embed and /api/chat accept options.num_thread
    return {"num_thread": threads}


def _cfg_get(config, key: str, default=None):
    try:
        if config is not None and hasattr(config, "get"):
            return config.get(key, default)
    except Exception:
        pass
    return default


def effective_snapshot(config=None) -> dict:
    """Return resolved compute snapshot from Config (all keys, safe defaults)."""
    ncpu = cpu_count()
    cpu_t = resolve_threads(int(_cfg_get(config, "compute.cpu_threads", 0) or 0))
    return {
        "cpu_count": ncpu,
        "cpu_threads": cpu_t,
        "max_threads": int(_cfg_get(config, "performance.max_threads", 4) or 4),
        "cache_mb": int(_cfg_get(config, "performance.cache_size_mb", 256) or 256),
        "embed_batch": max(8, min(128, int(_cfg_get(config, "compute.embed_batch", 32) or 32))),
        "backend": str(_cfg_get(config, "compute.backend", "auto") or "auto"),
        "gpu_enabled": bool(_cfg_get(config, "compute.gpu_enabled", True)),
        "allow_igpu": bool(_cfg_get(config, "compute.allow_igpu", True)),
        "low_resource": bool(_cfg_get(config, "compute.low_resource_mode", False)),
    }


def ollama_options(config=None) -> dict:
    """Ollama options honoring cpu_threads + gpu_enabled/backend + low_resource."""
    snap = effective_snapshot(config)
    opts: dict = {"num_thread": snap["cpu_threads"]}
    # GPU offload: Ollama uses num_gpu (layers offloaded). 0 = CPU only.
    try:
        if not snap["gpu_enabled"] or snap["backend"] == "cpu":
            opts["num_gpu"] = 0
        elif snap["low_resource"]:
            opts["num_gpu"] = 0
    except Exception:
        pass
    return opts


def effective_embed_batch(config=None) -> int:
    """Embed batch honoring low_resource (halved, min 8)."""
    snap = effective_snapshot(config)
    b = snap["embed_batch"]
    if snap["low_resource"]:
        b = max(8, b // 2)
    return b


def should_use_llm_rerank(config=None) -> bool:
    """False in low_resource mode (use local overlap only)."""
    try:
        return not bool(_cfg_get(config, "compute.low_resource_mode", False))
    except Exception:
        return True


def apply_compute_settings(config=None, pool=None, cache=None) -> dict:
    """Apply settings system-wide. Safe to call repeatedly + on settings change.

    - torch threads = cpu_threads (or auto)
    - OMP/MKL env threads (process-wide, best-effort, only if not already set)
    - QThreadPool maxThreadCount = performance.max_threads
    - CacheManager budget from cache_size_mb (avg ~256KB/entry)
    Returns snapshot dict.
    """
    snap = effective_snapshot(config)
    # torch threads
    try:
        import torch

        torch.set_num_threads(max(1, snap["cpu_threads"]))
    except Exception:
        pass
    # native BLAS threads for numpy/sklearn/openmp (only set if unset)
    try:
        import os as _os

        for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            if not _os.environ.get(_k):
                _os.environ[_k] = str(max(1, snap["cpu_threads"]))
    except Exception:
        pass
    # thread pool
    try:
        if pool is not None and hasattr(pool, "setMaxThreadCount"):
            pool.setMaxThreadCount(max(1, snap["max_threads"]))
    except Exception:
        pass
    # disk/mem cache budget
    try:
        if cache is not None and hasattr(cache, "set_budget_mb"):
            cache.set_budget_mb(snap["cache_mb"])
        elif cache is not None and hasattr(cache, "max_entries"):
            cache.max_entries = max(64, snap["cache_mb"] * 4)
    except Exception:
        pass
    logger.info(
        "Compute applied: cpu %d/%d, pool %d, cache %dMB, batch %d, backend %s gpu=%s igpu=%s low=%s",
        snap["cpu_threads"], snap["cpu_count"], snap["max_threads"], snap["cache_mb"],
        snap["embed_batch"], snap["backend"], snap["gpu_enabled"], snap["allow_igpu"], snap["low_resource"],
    )
    return snap


# ------------------------------------------------------------------ #
# Hardware scan (Linux + Windows) + dynamic recommendation
# ------------------------------------------------------------------ #
def get_ram_gb() -> float:
    """Total physical RAM in GB. Never raises (0.0 = unknown)."""
    try:
        import psutil  # type: ignore

        return round(float(psutil.virtual_memory().total) / (1024**3), 1)
    except Exception:
        pass
    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        kb = int("".join(c for c in line if c.isdigit()) or 0)
                        return round(kb / 1024 / 1024, 1)
    except Exception:
        pass
    try:
        import ctypes

        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = _MS()
        st.dwLength = ctypes.sizeof(_MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return round(float(st.ullTotalPhys) / (1024**3), 1)
    except Exception:
        pass
    return 0.0


def get_cpu_info() -> dict:
    """Logical/physical cores + threads. Never raises."""
    out = {"logical": cpu_count(), "physical": 0, "threads_per_core": 0}
    try:
        import psutil  # type: ignore

        out["logical"] = int(psutil.cpu_count(logical=True) or out["logical"])
        out["physical"] = int(psutil.cpu_count(logical=False) or 0)
    except Exception:
        pass
    try:
        if out["physical"] > 0:
            out["threads_per_core"] = round(out["logical"] / out["physical"], 1)
    except Exception:
        pass
    return out


def _is_igpu_name(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in ("uhd", "iris", "intel", "radeon vega", "vega", "arc a", "mali", "adreno", "apple"))


def get_gpus() -> list:
    """List GPUs: [{name, vram_gb, kind, via}]. Never raises. Linux + Windows."""
    gpus: list = []
    seen: set = set()

    def _add(name: str, vram: float, kind: str, via: str):
        key = ((name or "").strip().lower(), round(float(vram or 0), 1))
        if not name or key in seen:
            return
        seen.add(key)
        gpus.append({"name": name.strip(), "vram_gb": round(float(vram or 0), 1),
                     "kind": kind, "via": via})

    # torch CUDA
    try:
        import torch

        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                try:
                    nm = torch.cuda.get_device_name(i)
                    vm = float(torch.cuda.get_device_properties(i).total_memory) / (1024**3)
                    _add(nm, vm, "discrete" if not _is_igpu_name(nm) else "igpu", "torch.cuda")
                except Exception:
                    continue
    except Exception:
        pass
    # nvidia-smi (both OSes when NVIDIA present)
    try:
        import shutil
        import subprocess

        exe = shutil.which("nvidia-smi")
        if exe:
            out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=8).stdout
            for line in (out or "").splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    try:
                        _add(parts[0], float(parts[1]) / 1024.0, "discrete", "nvidia-smi")
                    except Exception:
                        _add(parts[0], 0.0, "discrete", "nvidia-smi")
    except Exception:
        pass
    # Windows WMI video controllers
    try:
        if platform.system() == "Windows":
            import subprocess

            ps = ("Get-CimInstance Win32_VideoController | "
                  "Select-Object Name, AdapterRAM | Format-Table -HideTableHeaders")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=10).stdout
            for line in (out or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                toks = line.rsplit(None, 1)
                nm = toks[0] if toks else line
                vr = 0.0
                if len(toks) == 2:
                    try:
                        vr = float(int(toks[1])) / (1024**3)
                    except Exception:
                        vr = 0.0
                if nm and "microsoft basic" not in nm.lower():
                    _add(nm, vr, "igpu" if _is_igpu_name(nm) else "discrete", "wmi")
    except Exception:
        pass
    # Linux lspci hint (names only, size unknown)
    try:
        if platform.system() == "Linux":
            import shutil
            import subprocess

            exe = shutil.which("lspci")
            if exe:
                out = subprocess.run([exe, "-mm"], capture_output=True, text=True, timeout=8).stdout
                for line in (out or "").splitlines():
                    low = line.lower()
                    if "vga" in low or "3d controller" in low or "display controller" in low:
                        nm = line.split('"')[-2] if '"' in line else line.strip()[:80]
                        if nm:
                            _add(nm, 0.0, "igpu" if _is_igpu_name(nm) else "discrete", "lspci")
    except Exception:
        pass
    return gpus


def scan_hardware() -> dict:
    """Full hardware snapshot for Settings UI. Never raises."""
    try:
        base = detect_devices()
    except Exception:
        base = {}
    try:
        ram = get_ram_gb()
    except Exception:
        ram = 0.0
    try:
        cpu = get_cpu_info()
    except Exception:
        cpu = {"logical": cpu_count(), "physical": 0}
    try:
        gpus = get_gpus()
    except Exception:
        gpus = []
    base.update({"ram_gb": ram, "cpu": cpu, "gpus": gpus,
                 "discrete_gpu": any(g.get("kind") == "discrete" and (g.get("vram_gb") or 0) > 0 for g in gpus),
                 "has_gpu": len(gpus) > 0})
    return base


def recommend_settings(hw: dict | None = None) -> dict:
    """Dynamic recommendation from scanned hardware (formulas, not hardcoded tiers).

    Scales with RAM/CPU/VRAM: bigger box → bigger pool/cache/batch + GPU on;
    small box → conservative + low_resource. Returns settings dict + reasons.
    """
    hw = hw or scan_hardware()
    try:
        ncpu = int((hw.get("cpu") or {}).get("logical") or hw.get("cpu_count") or cpu_count())
    except Exception:
        ncpu = cpu_count()
    try:
        ram = float(hw.get("ram_gb") or 0.0)
    except Exception:
        ram = 0.0
    gpus = hw.get("gpus") or []
    disc = [g for g in gpus if g.get("kind") == "discrete"]
    try:
        max_vram = max([float(g.get("vram_gb") or 0) for g in disc], default=0.0)
    except Exception:
        max_vram = 0.0
    has_disc = len(disc) > 0 and max_vram > 0
    has_any_gpu = len(gpus) > 0

    # workers: fit CPU and RAM (no fixed tiers)
    if ram > 0:
        workers = min(ncpu, max(2, int(ram * 0.75)))
    else:
        workers = min(ncpu, 6)
    workers = max(2, min(16, workers))
    # cache: ~32MB per GB RAM, clamped
    cache = int(min(1024, max(128, (ram * 32) if ram > 0 else 256)) // 64 * 64)
    # embed batch: RAM-driven, boosted by discrete VRAM
    batch = 32
    if ram >= 24:
        batch = 64
    elif ram >= 12:
        batch = 48
    elif ram >= 8:
        batch = 32
    elif ram > 0:
        batch = 16
    if has_disc:
        batch = min(128, max(batch, 64 if max_vram >= 4 else 48))
        if max_vram >= 8:
            batch = 96
    # backend / gpu flags
    if has_disc:
        backend, gpu, igpu = "gpu", True, True
    elif has_any_gpu:
        backend, gpu, igpu = "auto", True, True
    else:
        backend, gpu, igpu = "cpu", False, False
    low = bool(ram > 0 and ram < 8 and not has_disc)

    reasons = [
        f"Detected {ncpu} CPU threads, {ram or 'unknown'} GB RAM, "
        f"{len(gpus)} GPU(s){f' (best VRAM {max_vram:.1f}GB)' if has_disc else ''}.",
        f"Workers {workers} fit CPU ({ncpu}) and RAM ({ram}GB).",
        f"Cache {cache}MB scales with RAM; batch {batch} balances speed vs memory.",
        ("Discrete GPU found → GPU offload on." if has_disc else
         "iGPU/display adapter only → auto backend, CPU-safe." if has_any_gpu else
         "No GPU → CPU-only (no failed CUDA calls)."),
    ]
    if low:
        reasons.append("Low RAM without discrete GPU → low-resource on (halved batch, local rerank).")
    return {"performance.max_threads": workers, "performance.cache_size_mb": cache,
            "compute.cpu_threads": 0, "compute.embed_batch": batch, "compute.backend": backend,
            "compute.gpu_enabled": gpu, "compute.allow_igpu": igpu,
            "compute.low_resource_mode": low, "_reasons": reasons,
            "_hardware": {"cpu_threads": ncpu, "ram_gb": ram,
                          "gpus": gpus, "max_vram_gb": max_vram}}

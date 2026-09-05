"""File stat and timestamp utilities.

Extracts accurate file creation (birth) time across platforms:
- Linux: uses the glibc ``statx`` syscall (STATX_BTIME = 0x800) into a
  safe 512-byte allocated buffer (kernel struct statx is 256 bytes) to prevent
  any buffer overflow, unpacking stx_btime at offset 0x50.
- macOS/BSD: uses ``st.st_birthtime``.
- Windows / Fallback: uses ``min(st.st_ctime, st.st_mtime)`` so that file
  moves/copies or inode status changes (ctime) on Linux do not masquerade as
  false creation dates when the content was created/modified earlier.
"""

from __future__ import annotations

import ctypes
import os
import struct
from datetime import datetime
from typing import Optional

_statx_func = None
try:
    _libc = ctypes.CDLL("libc.so.6", use_errno=True)
    if hasattr(_libc, "statx"):
        _statx_func = _libc.statx
        _statx_func.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_void_p,
        ]
        _statx_func.restype = ctypes.c_int
except Exception:
    _statx_func = None

# AT_FDCWD = -100, AT_SYMLINK_NOFOLLOW = 0x100, STATX_BTIME = 0x800
_AT_FDCWD = -100
_AT_SYMLINK_NOFOLLOW = 0x100
_STATX_BTIME = 0x800
# stx_mask is at byte 0 (<I), stx_btime tv_sec is at byte 0x50 (80, <q)
_STATX_BUF_SIZE = 512


def get_file_creation_date(filepath: str, fallback: Optional[datetime] = None) -> Optional[datetime]:
    """Return the true creation (birth) timestamp for the file.

    On Linux, attempts the modern ``statx`` syscall to read ``stx_btime``.
    If unavailable or unsupported by the underlying filesystem, falls back to
    ``st.st_birthtime`` or ``min(st.st_ctime, st.st_mtime)``.
    """
    if not filepath:
        return fallback

    if not os.path.exists(filepath):
        return fallback

    try:
        if _statx_func is not None:
            # Allocate 512 bytes: Linux kernel struct statx is 256 bytes (0x100).
            # This guarantees zero buffer overflow.
            buf = ctypes.create_string_buffer(_STATX_BUF_SIZE)
            path_bytes = filepath.encode("utf-8", errors="surrogateescape")
            res = _statx_func(_AT_FDCWD, path_bytes, _AT_SYMLINK_NOFOLLOW, _STATX_BTIME, buf)
            if res == 0:
                mask = struct.unpack_from("<I", buf, 0)[0]
                if mask & _STATX_BTIME:
                    btime_sec = struct.unpack_from("<q", buf, 0x50)[0]
                    if btime_sec > 0:
                        return datetime.fromtimestamp(btime_sec)

        st = os.stat(filepath)
        btime = getattr(st, "st_birthtime", None)
        if btime is not None and btime > 0:
            return datetime.fromtimestamp(btime)

        # On Linux/POSIX without btime: st_ctime changes on mv/cp/chmod.
        # A file cannot be modified before it was created, so min(ctime, mtime)
        # prevents false modern "creation" dates when old files are copied/moved.
        if st.st_ctime > 0 and st.st_mtime > 0:
            return datetime.fromtimestamp(min(st.st_ctime, st.st_mtime))
        elif st.st_ctime > 0:
            return datetime.fromtimestamp(st.st_ctime)
        elif st.st_mtime > 0:
            return datetime.fromtimestamp(st.st_mtime)

        return fallback
    except Exception:
        return fallback


def format_file_size(size_bytes: int | float | None, include_exact: bool = False) -> str:
    """Format a byte count into human-readable units (B, KB, MB, GB).

    Args:
        size_bytes: Byte count to format.
        include_exact: If True and size_bytes >= 1024, appends exact bytes in parentheses,
                       e.g. '1.5 MB (1,572,864 bytes)'.

    Returns:
        Formatted string such as '45.2 KB' or '1.0 MB (1,085,440 bytes)'.
    """
    if size_bytes is None:
        return "0 B"
    try:
        size = float(size_bytes)
    except (ValueError, TypeError):
        return "0 B"

    if size < 0:
        return "0 B"

    if size < 1024:
        formatted = f"{int(size)} B"
    elif size < 1024 * 1024:
        formatted = f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        formatted = f"{size / (1024 * 1024):.1f} MB"
    else:
        formatted = f"{size / (1024 * 1024 * 1024):.2f} GB"

    if include_exact and size >= 1024:
        return f"{formatted} ({int(size):,} bytes)"
    return formatted


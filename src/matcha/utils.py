"""UTF-8-safe text + private-path helpers.

Text helpers are ported from Agent-Reach ``utils/text.py`` + ``process.py``;
private-path discipline (symlink rejection, atomic owner-only writes, bounded
no-follow reads) is ported from Agent-Reach ``utils/paths.py`` (Phase 7,
strategy §17).
"""

import os
import re
import stat
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from matcha.errors import ConfigSecurityError

UTF8_ENV: dict[str, str] = {
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
}


def utf8_subprocess_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment that forces Python child processes into UTF-8 mode."""
    env = dict(base if base is not None else os.environ)
    env.update(UTF8_ENV)
    return env


_URL_CREDENTIALS_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]{0,19}://)[^/\s@]+@")
_BARE_USERINFO_RE = re.compile(r"(?<![A-Za-z0-9._%+\-])[^:/\s@]+:[^/\s@]+@(?=[A-Za-z0-9.\-\[])")
_URL_QUERY_SECRET_RE = re.compile(
    r"([?&#](?:"
    r"access[_-]?token|auth[_-]?token|token|bearer|"
    r"api[_-]?key|key|password|passwd|secret|"
    r"signature|sig|session(?:id)?|cookie|credential"
    r")=)[^&#\s]*",
    re.IGNORECASE,
)


def scrub_url_credentials(text: object) -> str:
    """Redact URL userinfo and sensitive query/fragment values from text."""
    scrubbed = _URL_CREDENTIALS_RE.sub(r"\1***@", str(text))
    scrubbed = _BARE_USERINFO_RE.sub("***@", scrubbed)
    return _URL_QUERY_SECRET_RE.sub(r"\1***", scrubbed)


# ── private-path discipline (strategy §17) ─────────────────────────────────


def ensure_no_symlink_path(path: str | Path, label: str = "path") -> Path:
    """Reject symlinks in the config tree without tripping on OS roots.

    Walks from the deepest *existing* ancestor down to the target: that
    ancestor itself and every tail component must not be a symlink, then the
    ancestor is trusted via ``realpath``. This is sound because an attacker
    can only plant symlinks in the tail (or in the ancestor itself when they
    own its parent — both checked); OS-level links like macOS
    ``/var -> /private/var`` are intermediates of a *trusted existing
    ancestor* and never false-positive. Raises
    :class:`~matcha.errors.ConfigSecurityError` on a symlink.
    """
    target = Path(path)
    current = target
    suffix: list[str] = []
    while True:
        if os.path.islink(current):
            raise ConfigSecurityError(f"{label} cannot pass through a symlink: {current}")
        if current.exists():
            break
        if current == current.parent:
            break
        suffix.append(current.name)
        current = current.parent
    real = Path(os.path.abspath(os.path.realpath(current)))
    for part in reversed(suffix):
        real = real / part
        if os.path.islink(real):
            raise ConfigSecurityError(f"{label} cannot pass through a symlink: {real}")
    return target


def make_private_dir(path: str | Path) -> Path:
    """Create a user-only (0700) directory, rejecting symlink components."""
    target = ensure_no_symlink_path(path, "private directory")
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    ensure_no_symlink_path(target, "private directory")
    if sys.platform != "win32":
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            dir_fd = os.open(target, flags)
        except OSError:
            return target
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(dir_fd, 0o700)
        finally:
            os.close(dir_fd)
    return target


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int = 0o600,
) -> Path:
    """Atomically replace ``path`` with owner-only text, never via a symlink.

    mkstemp beside the target (same filesystem → ``os.replace`` is atomic),
    ``fchmod`` 0600, ``fsync`` the data, re-check the parent + target for a
    symlink that could have appeared mid-serialization, then ``os.replace``
    and fsync the directory (``O_DIRECTORY``). A late target symlink is
    replaced by the rename itself rather than followed.
    """
    target = Path(path)
    parent = target.parent
    make_private_dir(parent)
    ensure_no_symlink_path(target, "target file")

    fd, tmp_name = tempfile.mkstemp(
        dir=str(parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        if os.name != "nt" and hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        handle = os.fdopen(fd, "w", encoding=encoding)
        fd = -1
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        ensure_no_symlink_path(parent, "parent directory")
        ensure_no_symlink_path(target, "target file")
        os.replace(tmp_path, target)

        if os.name != "nt" and hasattr(os, "O_DIRECTORY"):
            try:
                dir_fd = os.open(
                    parent,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                )
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
    except BaseException:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def read_small_text_no_follow(
    path: str | Path,
    *,
    max_bytes: int,
    encoding: str = "utf-8",
) -> str | None:
    """Read a bounded regular file, refusing every symlink component.

    Opens with ``O_NOFOLLOW``, verifies it is a regular file no larger than
    ``max_bytes``, reads at most ``max_bytes`` bytes, and re-checks the path
    for symlinks before returning. Returns ``None`` when the file is absent.
    """
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")

    target = ensure_no_symlink_path(path, "read path")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(target, flags)
    except FileNotFoundError:
        return None

    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ConfigSecurityError(f"read target is not a regular file: {target}")
        if file_stat.st_size > max_bytes:
            raise ConfigSecurityError(f"read target exceeds size limit: {target}")

        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise ConfigSecurityError(f"read target exceeds size limit: {target}")
        ensure_no_symlink_path(target, "read path")
    finally:
        os.close(fd)
    return payload.decode(encoding)

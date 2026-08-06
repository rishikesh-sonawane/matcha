"""Thin adapter to the optional ``agent-reach`` tool (strategy §6.5).

``agent-reach`` (``pip install agent-reach``) is an **installer + doctor +
config tool**, not a wrapper: after it installs upstream tools (OpenCLI,
mcporter/Exa, gh), agents call those tools directly. Matcha's sources already
call them directly via ``backends/`` — this module only *reuses agent-reach's
health signal* (``agent-reach doctor --json``) when it is present, and
**degrades to Matcha's own probes when it is absent** (F-14), logging a
one-time hint.

Probe discipline (strategy §6.5, verified against Agent-Reach v1.5.0):

- ``agent-reach --version`` is a side-effect-free existence probe.
- ``agent-reach doctor --json`` runs each channel's check; Agent-Reach builds
  those checks from read-only probes (loopback opencli status, ``gh
  --version``, read-only mcporter config), so invoking it is safe here — but
  it is still a subprocess, so a short TTL cache prevents re-running it in a
  loop.
- gh: never run ``gh auth status`` (writes a device-id file) — inspect
  ``hosts.yml`` / env tokens for credentials instead, with read-only env vars.
- ``~/.agent-reach/config.yaml`` is borrowed read-only (symlink-rejected,
  size-bounded) for ``seed_ai_config()``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from matcha.probe import probe_command
from matcha.utils import scrub_url_credentials, utf8_subprocess_env

logger = logging.getLogger(__name__)

_AGENT_REACH_DOCTOR_TIMEOUT = 30
_SNAPSHOT_TTL_SECONDS = 30.0
_MAX_CONFIG_BYTES = 1024 * 1024

_GH_READ_ONLY_ENV = {
    # gh creates ~/.local/state/gh/device-id even for --version unless
    # telemetry is disabled; these are documented gh environment controls.
    "GH_TELEMETRY": "false",
    "DO_NOT_TRACK": "true",
    "GH_NO_UPDATE_NOTIFIER": "1",
    "GH_NO_EXTENSION_UPDATE_NOTIFIER": "1",
}

#: Seed defaults for ``seed_ai_config()`` — Groq-compatible, openai-style.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"

# Module-level state is mutated without locks — safe today because
# agent_reach_io is single-threaded by convention (sources call their own
# backends directly; enrichment workers never call opencli_ready()). If that
# ever changes, guard these with a threading.Lock.
_hint_logged = False
_snapshot_ts = 0.0
_snapshot_value: dict[str, Any] | None = None


# ── availability + doctor snapshot ─────────────────────────────────────


def agent_reach_available() -> bool:
    """True when a healthy ``agent-reach`` binary is on PATH."""
    probe = probe_command("agent-reach", ["--version"], timeout=10, package="agent-reach")
    return probe.ok


def _log_one_time_hint() -> None:
    """Log the F-14 degradation hint exactly once per process."""
    global _hint_logged
    if _hint_logged:
        return
    _hint_logged = True
    # Warning (not info) so the F-14 hint is actually visible in CLI runs.
    logger.warning(
        "agent-reach not installed — Matcha uses its own probes (optional: pip install agent-reach)"
    )


def doctor_snapshot() -> dict[str, Any] | None:
    """Run ``agent-reach doctor --json`` and return ``{channel: report}``.

    Returns None when agent-reach is missing (one-time hint logged) or the
    snapshot cannot be obtained/parsed. Results are cached for
    ``_SNAPSHOT_TTL_SECONDS`` so repeated health reads don't spawn a
    subprocess each time.
    """
    global _snapshot_ts, _snapshot_value
    now = time.monotonic()
    if now - _snapshot_ts < _SNAPSHOT_TTL_SECONDS:
        return _snapshot_value

    value = _fetch_snapshot()
    _snapshot_ts, _snapshot_value = now, value
    return value


def _fetch_snapshot() -> dict[str, Any] | None:
    if not agent_reach_available():
        _log_one_time_hint()
        return None
    path = shutil.which("agent-reach")
    env = utf8_subprocess_env()
    try:
        proc = subprocess.run(
            [path, "doctor", "--json"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_AGENT_REACH_DOCTOR_TIMEOUT,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("agent-reach doctor failed: %s", e)
        return None
    payload = _parse_json_output((proc.stdout or "") + (proc.stderr or ""))
    if proc.returncode != 0 or not isinstance(payload, dict):
        logger.warning("agent-reach doctor returned an unusable snapshot")
        return None
    # Defense-in-depth: channel messages may echo configured URLs.
    return {str(k): _scrub_report(v) for k, v in payload.items()}


def _scrub_report(report: Any) -> Any:
    if isinstance(report, dict):
        scrubbed = dict(report)
        if isinstance(scrubbed.get("message"), str):
            scrubbed["message"] = scrub_url_credentials(scrubbed["message"])
        return scrubbed
    return report


# ── health signals (snapshot-first, own-probe fallback) ────────────────


def opencli_ready() -> bool:
    """OpenCLI bridge health — agent-reach snapshot first, own probe fallback.

    The snapshot reports an OpenCLI-backed channel as ``warn`` when the
    bridge is connected (login not live-verified), so ``warn``/``ok`` counts
    as ready. When the snapshot is absent or names no OpenCLI channel, fall
    back to Matcha's own loopback probe.
    """
    snapshot = doctor_snapshot()
    if snapshot:
        parsed = _opencli_ready_from_snapshot(snapshot)
        if parsed is not None:
            return parsed
    from matcha.sources.backends.opencli import opencli_status

    return opencli_status().ready


def _opencli_ready_from_snapshot(snapshot: dict[str, Any]) -> bool | None:
    """True/False from any OpenCLI-backed channel, else None (no such channel).

    Ready if ANY OpenCLI channel reports ok/warn — a single healthy channel
    means the bridge works, regardless of dict insertion order.
    """
    found_opencli = False
    for report in snapshot.values():
        if not isinstance(report, dict):
            continue
        backends = report.get("backends")
        is_opencli = isinstance(backends, list) and any(
            "opencli" in str(b).lower() for b in backends
        )
        if not is_opencli:
            continue
        found_opencli = True
        if report.get("status") in ("ok", "warn"):
            return True
    return False if found_opencli else None


def exa_search(query: str, num: int = 5) -> list[dict[str, Any]] | None:
    """Semantic web search via Exa — delegates to ``backends/exa.py``.

    ``backends/exa.py`` owns the verified dual-syntax ``mcporter call``
    runner, error-envelope detection and ``includeDomains`` retry guard, so
    this is a thin reuse point (code reuse over duplication).
    """
    from matcha.sources.backends.exa import exa_search as _exa_search

    return _exa_search(query, num=num)


# ── gh profile (optional, read-only) ───────────────────────────────────


def gh_profile(timeout: int = 15) -> dict[str, Any] | None:
    """GitHub CLI user profile (login/name/email) — None when unavailable.

    Read-only discipline (strategy §6.5): probe ``gh --version`` with
    telemetry disabled, and confirm credentials via env tokens or ``hosts.yml``
    — never run ``gh auth status`` (it writes a device-id file).
    """
    probe = probe_command("gh", ["--version"], timeout=10, package="gh", env=_GH_READ_ONLY_ENV)
    if not probe.ok:
        return None
    if not _gh_credentials_present():
        return None
    path = shutil.which("gh")
    env = utf8_subprocess_env()
    env.update(_GH_READ_ONLY_ENV)
    try:
        proc = subprocess.run(
            [path, "api", "user"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("gh api user failed: %s", e)
        return None
    if proc.returncode != 0:
        logger.info("gh api user failed (exit %s)", proc.returncode)
        return None
    payload = _parse_json_output(proc.stdout or "")
    if not isinstance(payload, dict):
        return None
    return {
        key: payload[key] for key in ("login", "name", "email") if key in payload and payload[key]
    }


def _gh_credentials_present() -> bool:
    """Auth signal without executing gh: explicit env tokens OR hosts.yml.

    Mirrors Agent-Reach's reference ``github.py`` (explicit env credentials
    accepted before the file check) so automation using ``GH_TOKEN`` /
    ``GITHUB_TOKEN`` is not wrongly reported as unauthenticated.
    """
    if any(os.environ.get(name) for name in ("GH_TOKEN", "GITHUB_TOKEN")):
        return True
    return _gh_hosts_configured()


def _gh_hosts_path() -> Path:
    override = os.environ.get("GH_CONFIG_DIR")
    if override:
        return Path(os.path.abspath(os.path.expanduser(override))) / "hosts.yml"
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "gh" / "hosts.yml"
    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        if app_data:
            return Path(app_data) / "GitHub CLI" / "hosts.yml"
    return Path.home() / ".config" / "gh" / "hosts.yml"


def _gh_hosts_configured() -> bool:
    """Inspect github.com's hosts.yml entry without executing gh."""
    path = _gh_hosts_path()
    if path.is_symlink():
        return False
    try:
        raw = path.read_bytes()[: _MAX_CONFIG_BYTES + 1]
    except OSError:
        return False
    if len(raw) > _MAX_CONFIG_BYTES:
        return False
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        return False
    if not isinstance(payload, dict):
        return False
    host = payload.get("github.com")
    if not isinstance(host, dict):
        return False
    users = host.get("users")
    if users is not None and not isinstance(users, dict):
        return False
    return bool(host.get("oauth_token") or host.get("user") or users)


# ── AI config seeding (borrow groq key) ────────────────────────────────


def seed_ai_config(config_path: str | Path | None = None) -> dict[str, Any] | None:
    """Borrow ``groq_api_key`` from agent-reach's config.yaml (read-only).

    Returns ``{ai_key, ai_url, ai_model}`` — ready to hand to
    ``matcha.ai.configure_ai`` — or None when the key is absent. The file is
    read read-only; symlinks and oversized files are rejected (credential
    boundary).
    """
    if config_path:
        path = Path(os.path.abspath(os.path.expanduser(str(config_path))))
    else:
        path = Path.home() / ".agent-reach" / "config.yaml"
    if path.is_symlink():
        return None
    try:
        raw = path.read_bytes()[: _MAX_CONFIG_BYTES + 1]
    except OSError:
        return None
    if len(raw) > _MAX_CONFIG_BYTES:
        return None
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError):
        return None
    if not isinstance(payload, dict):
        return None
    key = payload.get("groq_api_key")
    if not isinstance(key, str) or not key.strip():
        return None
    return {"ai_key": key.strip(), "ai_url": GROQ_BASE_URL, "ai_model": GROQ_MODEL}


# ── tolerant JSON helper ───────────────────────────────────────────────


def _parse_json_output(text: str) -> Any | None:
    """Tolerant JSON extraction: strips ANSI codes and leading noise."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
    starts = sorted(i for i in (text.find("["), text.find("{")) if i != -1)
    for start in starts:
        try:
            return json.JSONDecoder().raw_decode(text[start:])[0]
        except (json.JSONDecodeError, ValueError):
            continue
    return None

"""Source base class — job-source availability checking.

Each source represents a job platform/aggregator (LinkedIn, Indeed, Naukri,
RemoteOK, Web Search, Career Sites, SerpAPI) and provides:

- ``check(config)`` — is the upstream backend available right now?
- ``search(query, location, **kwargs)`` — acquire jobs (Phase 0 delegates to
  the legacy 1.x parser functions, unchanged behavior).

Backend routing semantics (ported from Agent-Reach channels/base.py):

- ``backends`` is an ORDERED candidate list: backends[0] is the preferred
  backend, the rest are fallbacks. "Switching backends" means reordering this
  list (or a user override) — not rewriting code.
- check() must REALLY probe the upstream and set ``self.active_backend`` to the
  backend actually serving this source right now (None when nothing usable is
  found). ``shutil.which()`` alone is NOT proof of health — a stale venv shim
  passes which() but cannot execute (see matcha.probe).
- Users can force a backend with the config key ``scrapers.<source>_backend``
  (or env var ``<SOURCE>_BACKEND``); ordered_backends() applies it. Unknown
  values are ignored so a stale override can never hide working backends.
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import requests

from matcha.models import ScraperResult

logger = logging.getLogger(__name__)


def probe_url(url: str, timeout: int = 6) -> tuple[str, str]:
    """Lightweight, side-effect-free HTTP probe for Source.check().

    Bounded time, no retries and streamed bodies so doctor stays fast even
    when a site is down. Returns (status, message) with status in
    ok|warn|error (warn = reachable but gated).
    """
    try:
        resp = requests.get(url, timeout=timeout, stream=True)
        status = resp.status_code
        resp.close()
    except requests.Timeout:
        return "error", f"timed out after {timeout}s"
    except requests.ConnectionError as e:
        return "error", f"connection failed: {e}"
    except requests.RequestException as e:
        return "error", f"request failed: {e}"
    if status == 200:
        return "ok", "HTTP 200"
    if status in (401, 403):
        return "warn", f"HTTP {status} (login / anti-bot gated)"
    return "error", f"HTTP {status}"


class Source(ABC):
    """Base class for all job sources."""

    name: str = ""  # registry key, e.g. "linkedin"
    description: str = ""  # human label, e.g. "LinkedIn — jobs via guest API"
    backends: list[str] = []  # ordered candidates — backends[0] = preferred
    tier: int = 0  # 0 = zero-config, 1 = needs free key / login, 2 = needs setup
    enabled_by_default: bool = True

    #: Backend currently serving this source; set by check(), None = unavailable.
    active_backend: str | None = None

    @abstractmethod
    def check(self, config: dict[str, Any] | None = None) -> tuple[str, str]:
        """Probe this source; return (status, message) and set active_backend.

        Status must be one of ok|warn|off|error.
        """
        ...

    @abstractmethod
    def search(self, query: str, location: str = "", **kwargs: Any) -> ScraperResult:
        """Acquire jobs for this source (unchanged 1.x behavior in Phase 0)."""
        ...

    def ordered_backends(self, config: dict[str, Any] | None = None) -> list[str]:
        """Candidate backends in probe order, honoring the user override.

        The config key ``scrapers.<source>_backend`` (env ``<SOURCE>_BACKEND``)
        moves the named backend to the front of the list; unknown values are
        ignored so a stale override can never hide working backends.
        """
        candidates = list(self.backends)
        override: str | None = None
        if config and isinstance(config, dict):
            scrapers_cfg = config.get("scrapers")
            if isinstance(scrapers_cfg, dict):
                override = scrapers_cfg.get(f"{self.name}_backend")
        if not override:
            override = os.environ.get(f"{self.name.upper()}_BACKEND")
        if override:
            for i, b in enumerate(candidates):
                if b == override or b.startswith(override):
                    candidates.insert(0, candidates.pop(i))
                    break
        return candidates

    @staticmethod
    def _scrapers_config(config: dict[str, Any] | None) -> dict[str, Any]:
        """Pull the ``scrapers`` subsection out of a settings dict."""
        if config and isinstance(config, dict):
            cfg = config.get("scrapers")
            if isinstance(cfg, dict):
                return cfg
        return {}

    @staticmethod
    def _ddgs_status(ddgs_imported: bool) -> tuple[str, str]:
        """Shared check for DDGS-backed sources: library availability."""
        if not ddgs_imported:
            return "error", "ddgs library not installed (pip install ddgs)"
        return "ok", "DDGS library available (network checked at search time)"

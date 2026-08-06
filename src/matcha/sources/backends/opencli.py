"""OpenCLI browser-bridge backend (strategy §6.3; probe ported from Agent-Reach).

OpenCLI (``npm install -g @jackwener/opencli``) drives the user's real Chrome
via a browser extension + loopback daemon, reusing existing login sessions.
It is the premium backend for LinkedIn and Indeed::

    opencli linkedin search "<q>" --location "<loc>" --date-posted week -f json
    opencli linkedin job-detail "<url>" -f json
    opencli indeed search "<q>" --location "<loc>" --fromage 7 -f json
    opencli indeed job "<jk>" -f json

Rules (verified against OpenCLI 1.8.4, 2026-08-06):

- **Desktop-only**: requires a real (non-headless) Chrome with the OpenCLI
  extension loaded; it cannot run on headless servers.
- **Health checks must NEVER run ``opencli doctor``** — it auto-starts the
  daemon. Probe ``opencli --version`` (stripping the stale
  ``OPENCLI_DAEMON_PORT`` env var that OpenCLIApp 0.1.35 injected into every
  child) and read live daemon state from the loopback endpoint
  ``http://127.0.0.1:19825/status`` with header ``X-OpenCLI: 1``. Only
  ``extensionConnected: true`` proves the browser actually loaded the
  extension — disk files are deliberately not enough.
- **Consent-gated**: used only after the user opts in via ``matcha
  --configure``, which writes ``linkedin_consent`` / ``indeed_consent`` into
  config.json (flat) or the ``scrapers`` YAML subsection.
- ``-f json`` emits ``JSON.stringify(data, null, 2)`` (``src/output.ts``): a
  bare row array for search commands, possibly wrapped in ``{rows: [...]}``
  for composite commands — the parsers here accept both.

Row shapes (locked from OpenCLI adapter sources, same date):
- linkedin search: rank, title, company, location, listed, salary, url
  (+ description/apply_url when ``--details``)
- linkedin job-detail: title, company, location, workplace_type, job_type,
  applicants, listed, apply_url, company_url, url, description (no salary)
- indeed search: rank, id, title, company, location, salary, tags, url
- indeed job: id, title, company, location, salary, job_type, description, url
"""

import json
import logging
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from typing import Any

from matcha.config import load_config
from matcha.probe import probe_command
from matcha.utils import utf8_subprocess_env

logger = logging.getLogger(__name__)

OPENCLI_PACKAGE = "@jackwener/opencli"
OPENCLI_EXTENSION_ID = "ildkmabpimmkaediidaifkhjpohdnifk"
OPENCLI_EXTENSION_URL = f"https://chromewebstore.google.com/detail/opencli/{OPENCLI_EXTENSION_ID}"

_OPENCLI_DAEMON_STATUS_URL = "http://127.0.0.1:19825/status"
_MAX_DAEMON_STATUS_BYTES = 64 * 1024

#: OpenCLIApp 0.1.35 injected this now-unsupported variable into every child;
#: OpenCLI >= 1.8.5 rejects it before even handling ``--version``. Doctor is a
#: read-only observer, so strip the stale app setting only from child probes.
_UNSUPPORTED_APP_ENV = ("OPENCLI_DAEMON_PORT",)

#: consent config keys (strategy §6.3; resolved F-130): flat keys in
#: config.json or ``scrapers.<key>`` in the settings YAML.
_CONSENT_KEYS = {
    "linkedin": "linkedin_consent",
    "indeed": "indeed_consent",
}


# ── Probe (side-effect free) ────────────────────────────────────────────


def _fetch_daemon_status(timeout: int = 2) -> dict[str, Any] | None:
    """Read OpenCLI's loopback status endpoint without starting the CLI."""
    request = urllib.request.Request(
        _OPENCLI_DAEMON_STATUS_URL,
        headers={"X-OpenCLI": "1"},
        method="GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=min(timeout, 2)) as response:
            raw = response.read(_MAX_DAEMON_STATUS_BYTES + 1)
    except Exception:  # noqa: BLE001 — network probe must never raise
        return None
    if len(raw) > _MAX_DAEMON_STATUS_BYTES:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return None
    return payload


@dataclass
class OpenCLIStatus:
    installed: bool = False
    broken: bool = False
    daemon_running: bool = False
    extension_connected: bool = False
    version: str = ""
    hint: str = ""

    @property
    def ready(self) -> bool:
        """True only when the backend is provably usable right now.

        Only a live daemon connection proves that a browser loaded and
        enabled the extension. Disk files alone are deliberately not enough.
        """
        return self.installed and not self.broken and self.extension_connected


def opencli_status(timeout: int = 10) -> OpenCLIStatus:
    """Probe OpenCLI install + daemon/extension state without side effects.

    Never runs ``opencli doctor`` (auto-starts the daemon): ``--version`` is
    the only side-effect-free CLI fast path; live state comes from the
    loopback daemon endpoint.
    """
    version_probe = probe_command(
        "opencli",
        ["--version"],
        timeout=timeout,
        package=OPENCLI_PACKAGE,
        remove_env=_UNSUPPORTED_APP_ENV,
    )
    if version_probe.status == "missing":
        return OpenCLIStatus(
            installed=False,
            hint=(
                f"OpenCLI is not installed. Install it with:\n  npm install -g {OPENCLI_PACKAGE}"
            ),
        )
    if not version_probe.ok:
        return OpenCLIStatus(
            installed=True,
            broken=True,
            hint=(
                "The opencli command exists but cannot execute (broken node "
                "environment). Reinstall it with:\n"
                f"  npm install -g {OPENCLI_PACKAGE}"
            ),
        )

    st = OpenCLIStatus(installed=True, version=version_probe.output.strip())
    daemon_status = _fetch_daemon_status(timeout)
    if daemon_status is not None:
        st.daemon_running = True
        st.extension_connected = bool(daemon_status.get("extensionConnected"))

    if not st.extension_connected:
        if st.daemon_running:
            st.hint = (
                "OpenCLI is installed and its daemon is running, but no "
                "browser extension is connected. Open Chrome with the OpenCLI "
                "extension enabled, then run a command to verify."
            )
        else:
            st.hint = (
                "OpenCLI is installed but its browser bridge is not running. "
                "Start Chrome with the OpenCLI extension enabled "
                f"({OPENCLI_EXTENSION_URL}), or run `opencli browser init`."
            )
    return st


def opencli_summary(st: OpenCLIStatus) -> str:
    """One-line state description for doctor / configure output."""
    if not st.installed:
        return "OpenCLI not installed"
    if st.broken:
        return "OpenCLI installed but cannot execute (broken node environment)"
    if st.extension_connected:
        return f"OpenCLI ready (browser login sessions, v{st.version})"
    if st.daemon_running:
        return "OpenCLI daemon running, waiting for a connected browser extension"
    return "OpenCLI installed (browser bridge not running)"


# ── Consent ─────────────────────────────────────────────────────────────


def consent_granted(config: dict[str, Any] | None, source: str) -> bool:
    """True when the user opted in to OpenCLI for ``source``.

    Reads the flat config.json key (``linkedin_consent``) or the
    ``scrapers.<key>`` YAML subsection; the passed ``config`` (e.g. doctor's
    settings dict) wins over the on-disk config when it carries the key.
    Absent anywhere → False (consent is never implied).
    """
    key = _CONSENT_KEYS.get(source)
    if not key:
        return False
    if config:
        scrapers = config.get("scrapers")
        if isinstance(scrapers, dict) and key in scrapers:
            return bool(scrapers[key])
        if key in config:
            return bool(config[key])
    return bool(load_config().get(key))


def _opencli_should_run(config: dict[str, Any] | None, source: str) -> bool:
    """Gate for using the OpenCLI backend at search time: consented + healthy."""
    if not consent_granted(config, source):
        return False
    return opencli_status().ready


# ── Command runner ──────────────────────────────────────────────────────


def run_opencli(args: list[str], timeout: int = 60) -> dict[str, Any]:
    """Run ``opencli <args>`` and return a normalized result dict.

    Returns ``{"ok": bool, "rows": [...], "error": str, "raw": str}``.
    ``rows`` holds parsed row dicts ([] when the command produced none);
    ``error`` is a human message when ``ok`` is False (BROWSER_CONNECT
    failures and non-JSON output included).
    """
    path = shutil.which("opencli")
    if not path:
        return {"ok": False, "rows": [], "error": "opencli not installed", "raw": ""}

    cmd: list[str] = [path, *args, "-f", "json"]

    env = utf8_subprocess_env()
    env.pop("OPENCLI_DAEMON_PORT", None)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "rows": [], "error": f"opencli timed out after {timeout}s", "raw": ""}
    except OSError as e:
        return {"ok": False, "rows": [], "error": f"opencli failed to run: {e}", "raw": ""}

    stdout = proc.stdout or ""
    raw = stdout + (proc.stderr or "")
    if proc.returncode != 0:
        return {"ok": False, "rows": [], "error": _extract_error(raw, proc.returncode), "raw": raw}

    payload = _parse_json_output(stdout)
    if payload is None:
        return {"ok": False, "rows": [], "error": "opencli returned non-JSON output", "raw": raw}
    return {"ok": True, "rows": _extract_rows(payload), "error": "", "raw": raw}


def _extract_error(raw: str, code: int) -> str:
    """Pull a readable message out of OpenCLI's error output (usually YAML).

    A BROWSER_CONNECT failure prints ``ok: false / error: / code: ... /
    message: ...`` — grab the message line; fall back to the raw tail.
    """
    message = re.search(r"^\s*message:\s*(.+)$", raw, re.MULTILINE)
    if message:
        return f"opencli exited {code}: {message.group(1).strip().strip(chr(34))}"
    return f"opencli exited {code}: {raw.strip()[:300]}"


def _parse_json_output(text: str) -> Any | None:
    """Tolerant JSON extraction: strips ANSI codes and leading noise."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    for start in starts:
        try:
            return json.JSONDecoder().raw_decode(text[start:])[0]
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    """Normalize a command payload into a row list.

    Accepts a bare array (search commands) or a dict wrapping one under
    ``rows`` / ``data`` / ``results`` / ``items`` (composite commands).
    """
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "data", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


# ── Detail commands (enrichment, strategy §8) ──────────────────────────


def linkedin_job_detail(url: str, timeout: int = 30) -> dict[str, Any] | None:
    """Fetch one LinkedIn job detail row via ``opencli linkedin job-detail``.

    Returns the detail dict (title, company, location, workplace_type,
    job_type, applicants, listed, apply_url, company_url, url, description)
    or None when the command fails / yields no rows. **No salary** (F-06).
    """
    result = run_opencli(["linkedin", "job-detail", url], timeout=timeout)
    if not result["ok"] or not result["rows"]:
        return None
    return result["rows"][0]


def indeed_job_detail(job_key: str, timeout: int = 30) -> dict[str, Any] | None:
    """Fetch one Indeed job detail row via ``opencli indeed job <jk>``.

    Returns the detail dict (id, title, company, location, salary, job_type,
    description, url) or None when the command fails / yields no rows.
    """
    result = run_opencli(["indeed", "job", job_key], timeout=timeout)
    if not result["ok"] or not result["rows"]:
        return None
    return result["rows"][0]

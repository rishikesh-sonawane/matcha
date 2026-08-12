"""Exa semantic search backend via mcporter (strategy §6.2/§6.3).

Exa (``https://mcp.exa.ai/mcp``, exposed through the ``mcporter`` MCP client)
is the premium backend for Web Search: clean semantic results with
publishedDate/score instead of regex-guessed snippets. The free tier needs no
API key.

Probing (strategy §6.3, verified): never start ``mcporter`` just to check
state — inspect its config files read-only (see ``mcporter.py``). A configured
``exa`` server is a *routing* signal, not proof the remote service is live, so
doctor reports ``warn`` (not ``ok``) for it; search still attempts it and
degrades to DDGS on any failure.

Command syntax: mcporter's CLI was rewritten upstream (``wshobson/mcporter``
0.7.x DSL → ``openclaw/mcporter`` 0.8+ ``key=value`` args) and 0.13+
defaults to human-readable text, so calls pass ``--output json`` to keep
parsing reliable. Each syntax is tried with and without the flag, so the
backend works regardless of which generation is installed.

Current Exa MCP server contract (verified live): ``web_search_exa`` accepts
ONLY ``query`` + ``numResults`` (``includeDomains`` / ``startPublishedDate``
are silently ignored) and returns results as rendered text blocks
(``Title:``/``URL:``/``Published:``/``Author:``/``Highlights:`` separated by
``---``) rather than a structured ``results`` array. Queries are phrased with
"job posting" to steer Exa toward postings instead of LinkedIn people
profiles; recency is enforced client-side from the parsed ``publishedDate``.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from typing import Any

from matcha.sources.backends.mcporter import (
    McporterConfigError,
    inspect_mcporter_config,
)
from matcha.utils import utf8_subprocess_env

logger = logging.getLogger(__name__)

EXA_SERVER_NAME = "exa"
EXA_MCP_URL = "https://mcp.exa.ai/mcp"
EXA_TOOL = "web_search_exa"

_MCPORTER_TIMEOUT = 30


def exa_status(config: dict[str, Any] | None = None) -> tuple[str, str]:
    """Probe the Exa backend without side effects.

    Returns (status, message) with status in ok|warn|off|error:
    - off: mcporter not installed (with install + configure hints)
    - warn: exa configured but not live-verified (doctor never starts the
      remote MCP service); or exa hidden behind un-expanded editor imports
    - error: mcporter config present but untrustworthy
    """
    del config  # exa needs no config — setup is mcporter-file driven
    if not shutil.which("mcporter"):
        return (
            "off",
            "Exa backend needs mcporter + Exa MCP. Install:\n"
            "  npm install -g mcporter\n"
            f"  mcporter config add {EXA_SERVER_NAME} {EXA_MCP_URL} --scope home",
        )
    try:
        inspection = inspect_mcporter_config()
    except McporterConfigError as exc:
        return "error", f"mcporter config check failed: {exc}"
    if EXA_SERVER_NAME in inspection.server_names:
        return (
            "warn",
            "Exa is configured in mcporter, but doctor does not start the "
            "remote service to verify it — search will try it and fall back to DDGS.",
        )
    if inspection.imports_unchecked:
        return (
            "warn",
            "mcporter config enables editor imports; doctor does not expand "
            "them (credential boundary), so Exa may be configured there unverified.",
        )
    return (
        "off",
        "mcporter is installed but Exa is not configured. Run:\n"
        f"  mcporter config add {EXA_SERVER_NAME} {EXA_MCP_URL} --scope home",
    )


def exa_configured() -> bool:
    """True when the Exa server appears in the effective mcporter config.

    Read-only (never starts mcporter); any config error counts as not
    configured so search falls back to DDGS.
    """
    try:
        return EXA_SERVER_NAME in inspect_mcporter_config().server_names
    except McporterConfigError:
        return False


def exa_search(
    query: str,
    location: str = "",
    days: int | None = None,
    num: int = 5,
    timeout: int = _MCPORTER_TIMEOUT,
) -> list[dict[str, Any]] | None:
    """Run an Exa semantic search for job postings; None on any failure.

    Returns raw result rows ({title, url, publishedDate, author, text, ...})
    so the source module maps them with their own helpers. The current Exa
    MCP server exposes only query/numResults, so the query is phrased with
    "job posting" to target postings and recency is enforced client-side
    from the parsed ``publishedDate`` (see the web source's recency gate).
    """
    del days  # startPublishedDate is ignored by the current Exa server
    text = f"{query} job posting {location}".strip() if location else f"{query} job posting"
    params: dict[str, Any] = {
        "query": text,
        "numResults": num,
    }

    result = run_mcporter_call(EXA_SERVER_NAME, EXA_TOOL, params, timeout=timeout)
    if not result["ok"]:
        logger.warning("Exa search failed: %s", result["error"])
        return None
    rows = result["rows"]
    if not rows:
        logger.info("Exa returned 0 results")
        return []
    return rows


# ── mcporter command runner (dual syntax) ──────────────────────────────


def run_mcporter_call(
    server: str,
    tool: str,
    params: dict[str, Any],
    timeout: int = _MCPORTER_TIMEOUT,
) -> dict[str, Any]:
    """Invoke ``mcporter call <server>.<tool> <params>`` and normalize output.

    Returns ``{"ok": bool, "rows": [...], "error": str, "raw": str}``. Tries
    the current ``openclaw/mcporter`` ``key=value`` argument form first, then
    the legacy 0.7.x ``server.tool(arg: value, ...)`` DSL on failure. The
    first (most informative) error is returned when both fail.
    """
    path = shutil.which("mcporter")
    if not path:
        return {"ok": False, "rows": [], "error": "mcporter not installed", "raw": ""}

    env = utf8_subprocess_env()
    # mcporter 0.13+ needs --output json (its default is human-readable
    # text); older generations return the raw JSON envelope and reject the
    # flag. Try each syntax both ways so either generation works.
    bases = [
        ("new", ["call", f"{server}.{tool}", *_format_new_args(params)]),
        ("legacy", ["call", f"{server}.{tool}({_format_legacy_dsl(params)})"]),
    ]
    attempts: list[tuple[str, list[str]]] = []
    for syntax, args in bases:
        attempts.append((syntax, [*args, "--output", "json"]))
        attempts.append((syntax, args))
    errors: list[str] = []
    # Session 28 (reviewer-caught): the whole call must stay inside the
    # caller's budget (the scraper batch abandons futures after
    # settings ``search.batch_timeout``, default 120s). Cap the TOTAL across
    # all 4 attempts to ``timeout`` — a hung Exa must not chain 4×30s and
    # starve the DDGS fallback for the entire run.
    deadline = time.monotonic() + timeout
    for syntax, cmd_args in attempts:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            errors.append(f"mcporter call exceeded its {timeout}s total budget")
            break
        try:
            proc = subprocess.run(
                [path, *cmd_args],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=remaining,
                env=env,
            )
        except subprocess.TimeoutExpired:
            errors.append(f"mcporter ({syntax} syntax) timed out after {remaining:.0f}s")
            break
        except OSError as e:
            errors.append(f"mcporter ({syntax} syntax) failed to run: {e}")
            break
        raw = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            errors.append(_extract_mcporter_error(raw, proc.returncode))
            continue  # try the other syntax
        payload = _parse_json_output(proc.stdout or "")
        if payload is None:
            errors.append("mcporter returned non-JSON output")
            continue
        # Exa error envelopes ({success: false, error: ...}) parse fine but
        # carry no results — report them as a failure, not an empty result.
        envelope_error = _envelope_error(payload)
        if envelope_error:
            errors.append(envelope_error)
            continue
        return {"ok": True, "rows": _extract_exa_results(payload), "error": "", "raw": raw}
    if not errors:
        errors.append("mcporter call failed")
    return {"ok": False, "rows": [], "error": errors[0], "raw": ""}


def _format_new_args(params: dict[str, Any]) -> list[str]:
    """mcporter >= 0.8 (openclaw): ``key=value`` positional args."""
    return [f"{key}={_format_value(value)}" for key, value in params.items()]


def _format_legacy_dsl(params: dict[str, Any]) -> str:
    """mcporter 0.7.x (wshobson): ``key: value, ...`` inside the call string."""
    return ", ".join(f"{key}: {_format_value(value)}" for key, value in params.items())


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_format_value(item) for item in value) + "]"
    return str(value)


def _extract_mcporter_error(raw: str, code: int) -> str:
    """Best-effort message extraction from mcporter failure output.

    mcporter (a Node CLI) can emit plain ``Error: ...`` text or structured
    JSON errors, so try both before falling back to a raw dump.
    """
    message = re.search(r"^Error:\s*(.+)$", raw, re.MULTILINE)
    if message:
        return f"mcporter exited {code}: {message.group(1).strip()[:200]}"
    payload = _parse_json_output(raw)
    nested = _find_error_message(payload) if payload is not None else None
    if nested:
        return f"mcporter exited {code}: {nested[:200]}"
    return f"mcporter exited {code}: {raw.strip()[:200]}"


def _find_error_message(node: Any, depth: int = 0) -> str | None:
    """Pull a human message out of a parsed error envelope (error/message keys)."""
    if depth > 4 or node is None:
        return None
    if isinstance(node, dict):
        for key in ("error", "message", "msg"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                found = _find_error_message(value, depth + 1)
                if found:
                    return found
        return None
    if isinstance(node, list):
        for item in node:
            found = _find_error_message(item, depth + 1)
            if found:
                return found
        return None
    if isinstance(node, str):
        parsed = _parse_json_output(node)
        if parsed is not None:
            return _find_error_message(parsed, depth + 1)
    return None


def _envelope_error(payload: Any) -> str | None:
    """A parsed dict with success/error keys and no results is an error envelope."""
    if not isinstance(payload, dict):
        return None
    if _walk_for_results(payload, depth=0) is not None:
        return None
    success = payload.get("success")
    if success is False or "error" in payload:
        return _find_error_message(payload) or "Exa returned an error envelope"
    return None


def _parse_json_output(text: str) -> Any | None:
    """Tolerant JSON extraction: strips ANSI codes and leading noise."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
    # Prefer the EARLIEST { or [ — an envelope dict with a nested results
    # array must win over its inner array (a naive tuple order would parse
    # "{...results": [...]}" as the array inside it).
    starts = sorted(i for i in (text.find("["), text.find("{")) if i != -1)
    for start in starts:
        try:
            return json.JSONDecoder().raw_decode(text[start:])[0]
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _extract_exa_results(payload: Any) -> list[dict[str, Any]]:
    """Find result rows inside an Exa/mcporter payload.

    Handles three shapes: the bare Exa envelope ({requestId, results: [...]}),
    MCP CLI wrappers that nest tool output ({content: [{text: "{...}"}]}), and
    the current Exa MCP server's rendered text blocks ({content: [{text:
    "Title: ...\\nURL: ..."}]}).
    """
    found = _walk_for_results(payload, depth=0)
    if isinstance(found, list):
        return [r for r in found if isinstance(r, dict)]
    text = _collect_content_text(payload)
    if text:
        return _parse_exa_text_blocks(text)
    return []


_EXA_BLOCK_SEPARATOR = re.compile(r"\n\s*---\s*\n")
_EXA_TEXT_BLOCK_RE = re.compile(
    r"^Title:\s*(?P<title>.+?)\n"
    r"URL:\s*(?P<url>\S+)\n"
    r"Published:\s*(?P<published>.*?)\n"
    r"Author:\s*(?P<author>.*?)\n"
    r"Highlights:\s*\n(?P<highlights>.*)$",
    re.DOTALL,
)
#: Lenient fallback: Exa may omit Author:/Published: (or reorder) — a real
#: posting must never be dropped because a secondary field is missing.
_EXA_TITLE_URL_RE = re.compile(
    r"^Title:\s*(?P<title>.+?)\nURL:\s*(?P<url>\S+)", re.DOTALL
)


def _collect_content_text(node: Any, depth: int = 0) -> str:
    """Concatenate MCP ``content`` text blocks (mcporter 0.13+ rendering)."""
    if depth > 4 or node is None:
        return ""
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            return node["text"]
        parts: list[str] = []
        for value in node.values():
            part = _collect_content_text(value, depth + 1)
            if part:
                parts.append(part)
        return "\n".join(parts)
    if isinstance(node, list):
        parts = []
        for item in node:
            part = _collect_content_text(item, depth + 1)
            if part:
                parts.append(part)
        return "\n".join(parts)
    return ""


def _parse_exa_text_blocks(text: str) -> list[dict[str, Any]]:
    """Parse the current Exa server's rendered result blocks into rows.

    Each block looks like::

        Title: AWS DevOps Engineer | Acme
        URL: https://jobs.acme.com/123
        Published: 2026-07-28T00:00:00.000Z
        Author: Acme
        Highlights:
        <page text>

    Blocks are separated by a line of ``---``. Missing/N-A fields are omitted
    so downstream mapping falls back to its own extraction helpers.
    """
    rows: list[dict[str, Any]] = []
    for block in _EXA_BLOCK_SEPARATOR.split(text):
        m = _EXA_TEXT_BLOCK_RE.match(block.strip())
        if not m:
            m = _EXA_TITLE_URL_RE.match(block.strip())
        if not m:
            continue
        row: dict[str, Any] = {
            "title": m.group("title").strip(),
            "url": m.group("url").strip(),
        }
        if "published" in m.groupdict():
            published = m.group("published").strip()
            if published and published != "N/A":
                row["publishedDate"] = published
        if "author" in m.groupdict():
            author = m.group("author").strip()
            if author and author != "N/A":
                row["author"] = author
        if "highlights" in m.groupdict():
            highlights = m.group("highlights").strip()
            if highlights:
                row["text"] = highlights
        rows.append(row)
    return rows


def _walk_for_results(node: Any, depth: int) -> Any:
    if depth > 4 or node is None:
        return None
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict):
                found = _walk_for_results(item, depth + 1)
                if found is not None:
                    return found
        return None
    if isinstance(node, dict):
        results = node.get("results")
        if isinstance(results, list):
            return results
        for value in node.values():
            found = _walk_for_results(value, depth + 1)
            if found is not None:
                return found
        return None
    if isinstance(node, str):
        # MCP CLI wrappers sometimes embed the tool result as a JSON string.
        parsed = _parse_json_output(node)
        if parsed is not None:
            return _walk_for_results(parsed, depth + 1)
    return None

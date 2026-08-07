"""Environment health checker — powered by the sources registry.

Each source knows how to check itself; doctor just collects the results
(ported from Agent-Reach agent_reach/doctor.py).

The report shape for ``--json`` is::

    {name: {status, name, message, tier, backends, active_backend}}  # per source
    {"ai": {status, name, message, provider, provider_label, known_provider,
             requires_key, key_set, url, model_best, model_fast, available}}

Every ``name`` in the dict is a job source registry key, plus the special
``"ai"`` entry (AI is not a source, but doctor is the one-stop setup
verifier: provider, models, key-set and availability in one place).
"""

import json
from typing import Any

from rich.markup import escape

from matcha.ai import PROVIDERS, ai_status
from matcha.sources import get_all_sources
from matcha.sources.breaker import circuit_status
from matcha.utils import scrub_url_credentials

_STATUS_ICONS: dict[str, str] = {
    "ok": "[green]ok[/green]",
    "warn": "[yellow]warn[/yellow]",
    "off": "[dim]off[/dim]",
    "error": "[red]error[/red]",
}

_TIER_LABELS: dict[int, str] = {
    0: "Ready to use (zero-config)",
    1: "Needs key / login",
    2: "Optional setup",
}


def check_all(config: dict[str, Any] | None = None) -> dict[str, dict]:
    """Check all sources (plus the special ``"ai"`` entry) and return the report.

    A single misbehaving source must never take the whole report down, so
    per-source exceptions degrade to status="error"; the AI entry gets the
    same guarantee.
    """
    results: dict[str, dict] = {}
    for src in get_all_sources():
        try:
            status, message = src.check(config)
            active = src.active_backend
        except Exception as e:  # noqa: BLE001 — doctor must survive any source
            # Sources are registry singletons: a stale active_backend from a
            # previous check must not leak into an errored result.
            status = "error"
            message = f"check failed: {e}"
            active = None
        # Doctor is the final output boundary for both expected source
        # messages and unexpected exceptions; scrub every path.
        message = scrub_url_credentials(message)
        # Phase 7 (strategy §6.7): the doctor reports circuit state. An open
        # circuit is surfaced in the message so the TUI/agent can act on it.
        circuit = circuit_status(src.name)
        if circuit.get("open"):
            message = f"{message} · circuit OPEN (cooldown until skip)"
        results[src.name] = {
            "status": status,
            "name": src.description,
            "message": message,
            "tier": src.tier,
            "backends": src.backends,
            "active_backend": active,
            "circuit": circuit,
        }
    # AI availability (strategy §10.2): provider, models, key-set. The key
    # itself never leaves ``ai_status`` — doctor only sees a boolean. The
    # resolved chain is env → config.json → settings.yaml → preset default
    # (the ``--config`` override passed to source checks is not threaded
    # through, by design). Same guarantee as sources: an unexpected failure
    # degrades to status="error" instead of crashing the report.
    try:
        results["ai"] = _ai_report(ai_status())
    except Exception as e:  # noqa: BLE001 — doctor must survive any failure
        results["ai"] = {
            "status": "error",
            "name": "AI matching",
            "message": f"AI status check failed: {e}",
            "provider": "",
            "provider_label": "Not configured",
            "known_provider": False,
            "requires_key": True,
            "key_set": False,
            "url": "",
            "model_best": "",
            "model_fast": "",
            "available": False,
        }
    return results


def _ai_report(ai: dict[str, Any]) -> dict[str, Any]:
    """Wrap the AI snapshot into the doctor report entry shape.

    The URL is scrubbed for credentials (doctor is the output boundary for
    every path, JSON included); the key never leaves ``ai_status``.
    """
    status, message = _ai_status_message(ai)
    label = str(ai.get("provider_label") or ai.get("provider") or "Not configured")
    return {
        "status": status,
        "name": f"AI matching — {label}",
        "message": message,
        "provider": ai.get("provider", ""),
        "provider_label": label,
        "known_provider": bool(ai.get("known_provider")),
        "requires_key": bool(ai.get("requires_key")),
        "key_set": bool(ai.get("key_set")),
        "url": scrub_url_credentials(ai.get("url", "")),
        "model_best": ai.get("model_best", ""),
        "model_fast": ai.get("model_fast", ""),
        "available": bool(ai.get("available")),
    }


def _ai_status_message(ai: dict[str, Any]) -> tuple[str, str]:
    """Map the AI snapshot to a doctor (status, message) pair.

    ``ok`` — fully wired; ``off`` — untouched (heuristic-only); ``warn`` —
    partially configured (e.g. a key set but no provider/url/model, or an
    unknown provider name).
    """
    provider = str(ai.get("provider") or "")
    known = bool(ai.get("known_provider"))
    requires_key = bool(ai.get("requires_key"))
    key_set = bool(ai.get("key_set"))
    url = str(ai.get("url") or "")
    model_best = str(ai.get("model_best") or "")
    model_fast = str(ai.get("model_fast") or "")
    label = str(ai.get("provider_label") or provider or "not configured")

    if ai.get("available"):
        parts = [f"provider {label}"]
        if model_best:
            parts.append(f"best {model_best}")
        if model_fast:
            parts.append(f"fast {model_fast}")
        parts.append("key set" if key_set else "no key needed (local)")
        return "ok", "AI available — " + " · ".join(parts)

    if not provider and not key_set and not url and not model_best:
        return (
            "off",
            "AI off — heuristic-only. Set $MINIMAX or run `matcha --configure`",
        )
    if provider and not known:
        return (
            "warn",
            f"Unknown AI provider {provider!r} — valid: {', '.join(sorted(PROVIDERS))}",
        )
    missing: list[str] = []
    if not provider:
        missing.append("provider")
    if not url:
        missing.append("API URL")
    if not model_best:
        missing.append("model")
    if requires_key and not key_set:
        missing.append("API key ($MINIMAX or --configure)")
    return "warn", "AI incomplete — missing: " + ", ".join(missing)


def format_report(results: dict[str, dict]) -> str:
    """Format results as a readable text report (with Rich markup)."""
    lines: list[str] = [
        "[bold cyan]Matcha Doctor — Source Health[/bold cyan]",
        "[cyan]" + "=" * 48 + "[/cyan]",
        (
            "Legend: [green]ok[/green] ready · [yellow]warn[/yellow] needs "
            "config/login · [red]error[/red] broken · [dim]off[/dim] disabled"
        ),
    ]
    # AI is not a job source — exclude it from the per-source tiers and the
    # ready-count below, and render it as its own section instead.
    source_results = [r for r in results.values() if "tier" in r]
    ok_count = sum(1 for r in source_results if r["status"] == "ok")
    total = len(source_results)

    for tier in (0, 1, 2):
        entries = [r for r in source_results if r["tier"] == tier]
        if not entries:
            continue
        lines.append("")
        lines.append(f"[bold]{_TIER_LABELS[tier]}[/bold]")
        for r in entries:
            lines.append(f"  {_STATUS_ICONS.get(r['status'], r['status'])} {_name_msg(r)}")

    if "ai" in results:
        ai = results["ai"]
        lines.append("")
        lines.append("[bold]AI matching[/bold]")
        lines.append(f"  {_STATUS_ICONS.get(ai['status'], ai['status'])} {_name_msg(ai)}")

    lines.append("")
    color = "green" if ok_count == total else ("yellow" if ok_count > 0 else "red")
    lines.append(f"Status: [{color}]{ok_count}/{total}[/{color}] sources ready")

    return "\n".join(lines)


def _name_msg(r: dict) -> str:
    """Render one source line; show the active backend when there is a choice."""
    text = f"[bold]{escape(r['name'])}[/bold] — {escape(r['message'])}"
    active = r.get("active_backend")
    if active and len(r.get("backends", [])) > 1:
        text += f" [dim](active backend: {escape(active)})[/dim]"
    return text


def report_to_json(results: dict[str, dict]) -> str:
    """Serialize the report for ``matcha doctor --json``."""
    return json.dumps(results, indent=2, default=str)

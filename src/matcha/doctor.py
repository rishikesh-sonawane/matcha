"""Environment health checker — powered by the sources registry.

Each source knows how to check itself; doctor just collects the results
(ported from Agent-Reach agent_reach/doctor.py).

The report shape for ``--json`` is::

    {name: {status, name, message, tier, backends, active_backend}}
"""

import json
from typing import Any

from rich.markup import escape

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
    """Check all sources and return the {name: report} dict.

    A single misbehaving source must never take the whole report down, so
    per-source exceptions degrade to status="error".
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
    return results


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
    ok_count = sum(1 for r in results.values() if r["status"] == "ok")
    total = len(results)

    for tier in (0, 1, 2):
        entries = [r for r in results.values() if r["tier"] == tier]
        if not entries:
            continue
        lines.append("")
        lines.append(f"[bold]{_TIER_LABELS[tier]}[/bold]")
        for r in entries:
            lines.append(f"  {_STATUS_ICONS.get(r['status'], r['status'])} {_name_msg(r)}")

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

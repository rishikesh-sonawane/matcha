"""Optional MCP server for Matcha (strategy §10.4/§13, Phase 6).

Exposes two read-only tools over the Model Context Protocol (stdio):

- ``matcha_status``  → per-source health report (``matcha doctor --json``).
- ``matcha_search``  → the full headless pipeline (profile → search → filter
  → rank → enrich) as structured JSON (same document as
  ``matcha search --json``).

The ``mcp`` package is **optional** (``pip install 'matcha[agent]'``): the
module imports it under a ``HAS_MCP`` guard and prints an install hint when
absent. Purely additive — Matcha never requires an MCP client. Mirrors
Agent-Reach's ``integrations/mcp_server.py`` (guard, JSON text output,
credential-scrubbed errors).

Run with: ``matcha mcp``
"""

import json
import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP

    HAS_MCP = True
except ImportError:
    HAS_MCP = False

INSTALL_HINT = "pip install 'matcha[agent]'  (installs the `mcp` package)"


def create_server() -> Any:
    """Build and return the FastMCP server (exits with a hint if mcp is absent)."""
    if not HAS_MCP:
        print(f"MCP not installed. Install: {INSTALL_HINT}", file=sys.stderr)
        sys.exit(1)

    mcp = FastMCP("matcha")

    @mcp.tool()
    def matcha_status() -> str:
        """Per-source health report as JSON — which backends are live right now."""
        from matcha.doctor import check_all, report_to_json
        from matcha.settings import load_settings

        results = check_all(config=load_settings())
        return report_to_json(results)

    @mcp.tool()
    def matcha_search(query: str, location: str = "", days: int = 7) -> str:
        """Ranked job search as JSON: {jobs: [{match_score, reasons, ...}], source_counts, filter_summary}."""
        from matcha.ai import check_ai_available
        from matcha.config import load_config, load_profile
        from matcha.main import build_search_payload, run_search
        from matcha.settings import load_settings

        profile = load_profile()
        if not profile:
            return json.dumps(
                {
                    "error": (
                        "No saved profile found. Run `matcha` once interactively to create one."
                    )
                },
                ensure_ascii=False,
            )
        settings = load_settings()
        ai_enabled = check_ai_available() and settings.get("ai", {}).get("enabled", True)
        try:
            payload = run_search(
                profile,
                query,
                location,
                days,
                settings,
                load_config(),
                ai_enabled=ai_enabled,
                quiet=True,
            )
            return json.dumps(
                build_search_payload(query, location, days, payload, command="mcp"),
                ensure_ascii=False,
            )
        except Exception as e:
            # Errors are scrubbed of any embedded credentials (strategy §6.6).
            from matcha.utils import scrub_url_credentials

            return json.dumps({"error": scrub_url_credentials(str(e))}, ensure_ascii=False)

    return mcp


def run() -> None:
    """Start the MCP server over stdio (the transport Claude/agents use)."""
    if not HAS_MCP:
        print(f"MCP not installed. Install: {INSTALL_HINT}", file=sys.stderr)
        sys.exit(1)
    create_server().run()

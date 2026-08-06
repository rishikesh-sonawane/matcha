"""Read-only helpers for interpreting mcporter configuration.

Ported from Agent-Reach ``channels/mcporter.py`` (the strategy's verified
design parent). mcporter (``npm install -g mcporter``) is the MCP client that
drives Exa semantic search.

**Credential-boundary rule (strategy §6.3, verified):** health checks must
NEVER start ``mcporter`` just to inspect state. Read the config files
read-only instead: an explicit ``MCPORTER_CONFIG`` is a single layer;
otherwise mcporter loads ``~/.mcporter/mcporter.json{,c}`` (first found) and
then ``<cwd>/config/mcporter.json`` (project entries override duplicate home
names). Only exact ``mcpServers`` names are returned. Editor ``imports`` are
deliberately NOT opened — doing so would widen the credential-read boundary,
so their presence is flagged as ``imports_unchecked`` instead.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

_MAX_CONFIG_BYTES = 1024 * 1024


class McporterConfigError(ValueError):
    """Raised when mcporter configuration is not trustworthy."""


@dataclass(frozen=True)
class McporterConfigInspection:
    """Minimal, non-secret routing facts from the mcporter config layers."""

    server_names: frozenset[str]
    source: str | None
    imports_unchecked: bool = False


def inspect_mcporter_config(
    root_dir: str | Path | None = None,
) -> McporterConfigInspection:
    """Read the effective local mcporter config without starting mcporter."""
    selected_layers = _select_config_layers(root_dir)
    if not selected_layers:
        return McporterConfigInspection(frozenset(), None)

    names: set[str] = set()
    imports_unchecked = False
    sources: list[str] = []
    for config_path, source in selected_layers:
        payload = _read_config_object(config_path)
        servers = payload.get("mcpServers")
        if not isinstance(servers, dict):
            raise McporterConfigError("mcporter config is missing the mcpServers object")

        for name, definition in servers.items():
            if not isinstance(name, str) or not name.strip():
                raise McporterConfigError("mcporter config contains an invalid server name")
            if not isinstance(definition, dict):
                raise McporterConfigError("mcporter server definitions must be objects")
            names.add(name.casefold())

        imports = payload.get("imports", _MISSING)
        if imports is _MISSING:
            # mcporter defaults to importing supported editor configs when the
            # key is omitted. Doctor intentionally does not open those files.
            imports_unchecked = True
        elif not isinstance(imports, list) or not all(isinstance(item, str) for item in imports):
            raise McporterConfigError("mcporter imports must be a list of strings")
        elif imports:
            imports_unchecked = True
        sources.append(source)

    return McporterConfigInspection(
        frozenset(names),
        "+".join(sources),
        imports_unchecked=imports_unchecked,
    )


def _select_config_layers(
    root_dir: str | Path | None,
) -> list[tuple[Path, str]]:
    root = Path(os.path.abspath(os.fspath(root_dir or Path.cwd())))
    explicit = os.environ.get("MCPORTER_CONFIG", "").strip()
    if explicit:
        expanded = Path(os.path.expanduser(explicit))
        if not expanded.is_absolute():
            expanded = root / expanded
        return [(Path(os.path.abspath(os.fspath(expanded))), "explicit")]

    layers: list[tuple[Path, str]] = []
    home_base = Path.home() / ".mcporter"
    for name in ("mcporter.json", "mcporter.jsonc"):
        candidate = home_base / name
        if candidate.exists() or candidate.is_symlink():
            layers.append((candidate, "home"))
            break

    project_path = root / "config" / "mcporter.json"
    if project_path.exists() or project_path.is_symlink():
        layers.append((project_path, "project"))
    return layers


_MISSING = object()


def _read_config_object(config_path: Path) -> dict:
    if config_path.is_symlink():
        raise McporterConfigError(
            "mcporter config is a symlink — refusing to read it (credential boundary)"
        )
    try:
        raw = config_path.read_bytes()[: _MAX_CONFIG_BYTES + 1]
    except OSError as e:
        raise McporterConfigError(f"mcporter config could not be read safely: {e}") from e
    if len(raw) > _MAX_CONFIG_BYTES:
        raise McporterConfigError("mcporter config exceeds 1MB — refusing to read it")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise McporterConfigError("mcporter config is not valid UTF-8 JSON") from e
    if not isinstance(payload, dict):
        raise McporterConfigError("mcporter config top level must be an object")
    return payload

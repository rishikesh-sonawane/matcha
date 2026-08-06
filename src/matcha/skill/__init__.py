"""Agent-skill package for Matcha (strategy §13, Phase 6).

Bundles the bilingual ``SKILL.md`` (package data) and the installer helpers
used by ``matcha skill --install/--uninstall``. Default destinations mirror
the de-facto agent skill locations: ``~/.agents/skills/matcha`` and
``~/.claude/skills/matcha`` (Agent-Reach's ``skill`` pattern).
"""

import shutil
from pathlib import Path

SOURCE_DIR = Path(__file__).parent
SKILL_FILENAME = "SKILL.md"


def source_skill_path() -> Path:
    """Path to the bundled SKILL.md (raises if package data is missing)."""
    return SOURCE_DIR / SKILL_FILENAME


def default_destinations() -> list[Path]:
    """Standard agent-skill install locations (home-relative)."""
    home = Path.home()
    return [
        home / ".agents" / "skills" / "matcha",
        home / ".claude" / "skills" / "matcha",
    ]


def install_skill(dest: str | Path) -> Path:
    """Copy SKILL.md into ``dest``; returns the written file path."""
    dest = Path(dest)
    src = source_skill_path()
    if not src.exists():
        raise FileNotFoundError(f"Skill source missing: {src}")
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / SKILL_FILENAME
    out.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return out


def uninstall_skill(dest: str | Path) -> bool:
    """Remove a previously installed skill directory; False if absent."""
    dest = Path(dest)
    if not dest.exists():
        return False
    shutil.rmtree(dest)
    return True

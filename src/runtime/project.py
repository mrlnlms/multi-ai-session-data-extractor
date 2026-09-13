"""Repository path discovery that is independent of script nesting depth."""

from pathlib import Path


def find_project_root(start: Path) -> Path:
    """Return the nearest ancestor containing the canonical project markers."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (
            (candidate / "src").is_dir()
            and (candidate / "README.md").is_file()
            and (candidate / "AGENTS.md").is_file()
        ):
            return candidate
    raise RuntimeError(f"Could not locate project root from {start}")

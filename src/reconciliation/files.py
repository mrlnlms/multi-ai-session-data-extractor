"""Filesystem helpers shared by reconcilers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def link_or_copy(source: Path, destination: Path) -> bool:
    """Materialize an immutable file without duplicating bytes when possible.

    Existing destinations are preserved. Hardlinks are attempted first and a
    metadata-preserving copy keeps the reconciler portable across filesystems.
    """
    if destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return True

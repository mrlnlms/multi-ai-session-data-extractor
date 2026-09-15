"""One-line, read-only archive baseline for a Codex SessionStart hook."""

from pathlib import Path
import sys


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from src.operations.archive_assurance import read_assurance

    print(read_assurance(root).compact())


if __name__ == "__main__":
    main()

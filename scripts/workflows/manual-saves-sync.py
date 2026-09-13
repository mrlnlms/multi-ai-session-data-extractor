#!/usr/bin/env python
"""Compatibility command for manual-save ingestion."""

from src.workflows.manual_saves import main


if __name__ == "__main__":
    raise SystemExit(main())

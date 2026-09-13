#!/usr/bin/env python
"""Compatibility command for the headless four-stage pipeline."""

from src.workflows.headless import main


if __name__ == "__main__":
    raise SystemExit(main())

"""Compatibility exports for shared workflow execution.

New code should import :mod:`src.workflows.execution` directly. This module
remains temporarily stable for dashboard extensions and external callers.
"""

from src.workflows.execution import *  # noqa: F401,F403

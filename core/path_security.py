"""Path security helpers for neutralizing tainted path inputs.

These helpers implement the canonical remediation for CodeQL ``py/path-injection``:
normalize the path with :func:`os.path.realpath` (removes ``..`` segments and
resolves symlinks) and then verify the result is contained within a trusted root
before use. The normalization + containment check is the exact pattern recognized
by static path-injection analysis as neutralizing untrusted input.
"""
from __future__ import annotations

import os

from core.config import get_workspace_root

__all__ = ["UnsafePathError", "safe_join", "safe_workspace_path"]


class UnsafePathError(ValueError):
    """Raised when a path escapes its allowed root or is otherwise unsafe."""


def safe_join(root: str, *parts: str) -> str:
    """Join ``parts`` onto ``root`` and guarantee the result stays within ``root``.

    The joined path is normalized with :func:`os.path.realpath` and verified to be
    equal to, or nested under, the realpath of ``root``. This makes it safe to use in
    filesystem operations even when ``parts`` contain untrusted data (e.g. a task id
    taken from a URL).

    Raises:
        UnsafePathError: if the resulting path escapes ``root`` (path traversal).
    """
    root_real = os.path.realpath(root)
    joined = os.path.join(root_real, *parts)
    target_real = os.path.realpath(joined)
    prefix = root_real if root_real.endswith(os.sep) else root_real + os.sep
    if target_real != root_real and not target_real.startswith(prefix):
        raise UnsafePathError(f"Path escapes root directory: {joined!r}")
    return target_real


def safe_workspace_path(path: str, *, allowed_root: str | None = None) -> str:
    """Normalize a user-supplied workspace path and contain it within ``allowed_root``.

    ``allowed_root`` defaults to the trusted workspace root
    (:func:`core.config.get_workspace_root`, i.e. ``AGNES_WORKSPACE_ROOT`` or the
    operator's home directory). Container deployments should set
    ``AGNES_WORKSPACE_ROOT`` (e.g. ``/app``) to permit workspace locations outside
    the operator's home directory.
    """
    norm = os.path.realpath(os.path.abspath(path))
    root = allowed_root or get_workspace_root()
    root_real = os.path.realpath(root)
    prefix = root_real if root_real.endswith(os.sep) else root_real + os.sep
    if norm != root_real and not norm.startswith(prefix):
        raise UnsafePathError(f"Workspace path outside allowed root: {path!r}")
    return norm

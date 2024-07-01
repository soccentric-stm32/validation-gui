"""Build/version metadata (PKG-005)."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from hwval_studio import __version__


def _git_commit() -> str:
    env = os.environ.get("HWVAL_STUDIO_GIT_COMMIT")
    if env:
        return env
    try:
        root = Path(__file__).resolve().parents[2]
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _build_date() -> str:
    env = os.environ.get("HWVAL_STUDIO_BUILD_DATE")
    if env:
        return env
    return datetime.now(UTC).strftime("%Y-%m-%d")


VERSION = __version__
GIT_COMMIT = _git_commit()
BUILD_DATE = _build_date()


def version_string() -> str:
    commit = f" ({GIT_COMMIT})" if GIT_COMMIT else ""
    return f"{VERSION}{commit}, built {BUILD_DATE}"

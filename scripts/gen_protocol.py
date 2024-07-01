#!/usr/bin/env python3
"""Regenerate the Python HWLINK bindings from protocol/hwlink.fbs (GCON-004)."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "protocol" / "hwlink.fbs"
OUT = ROOT / "src" / "hwval_studio" / "protocol" / "generated"


def generate(flatc: str, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "__init__.py").write_text("")
    subprocess.run([flatc, "--python", "-o", str(target), str(SCHEMA)], check=True)
    package = target / "hwlink"
    (package / "__init__.py").write_text("")
    # flatc emits absolute imports for nested tables (`from hwlink.X import X`);
    # make them relative so the package can be bundled normally.
    for path in package.glob("*.py"):
        text = path.read_text()
        new = text.replace("from hwlink.", "from .")
        if new != text:
            path.write_text(new)


def replace_tree(source: Path, target: Path) -> None:
    """Swap ``source`` into ``target`` without deleting ``target`` first."""
    backup = target.with_name(target.name + ".old")
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        target.rename(backup)
    try:
        source.rename(target)
    except OSError:
        if backup.exists():
            backup.rename(target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flatc", default=shutil.which("flatc") or "flatc")
    args = parser.parse_args()
    if not SCHEMA.is_file():
        print(f"missing schema: {SCHEMA}", file=sys.stderr)
        return 1

    # Generate next to the target (same filesystem) and swap only on success,
    # so a missing or failing flatc never removes the committed bindings.
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".generated-", dir=OUT.parent))
    try:
        try:
            generate(args.flatc, tmp)
        except FileNotFoundError:
            print(
                f"flatc not found ({args.flatc}); install it or keep the "
                "committed generated bindings",
                file=sys.stderr,
            )
            return 1
        except subprocess.CalledProcessError as exc:
            print(f"flatc failed ({exc.returncode}); generated code not replaced", file=sys.stderr)
            return exc.returncode or 1
        replace_tree(tmp, OUT)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"generated {OUT / 'hwlink'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

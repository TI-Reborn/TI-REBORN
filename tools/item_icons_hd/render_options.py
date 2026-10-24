"""Portable Blender CLI parsing; anchor paths before scene initialization."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path


def parse(argv: Sequence[str], *, base: Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ids', type=int, nargs='*')
    parser.add_argument('--textures', type=Path)
    parser.add_argument('--samples', type=int, default=128)
    args = parser.parse_args(argv)
    for name in ('client', 'manifest', 'out', 'textures'):
        path = getattr(args, name)
        if path is not None:
            setattr(args, name, (base / path).resolve())
    return args

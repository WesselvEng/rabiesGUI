#!/usr/bin/env python3
"""Compatibility launcher for the unified RABIES GUI."""

from typing import Any

import rabies_gui_core as _gui_core

__all__ = [
    name for name in dir(_gui_core) if not name.startswith("_")
]


def __getattr__(name: str) -> Any:
    return getattr(_gui_core, name)


if __name__ == "__main__":
    _gui_core.main()

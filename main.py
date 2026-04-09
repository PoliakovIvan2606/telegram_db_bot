#!/usr/bin/env python3
"""Run from repo root: python main.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from bot.main import main

if __name__ == "__main__":
    main()

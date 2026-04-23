"""Make the repo root importable by pytest.

Running ``pytest`` from the repo root would normally not add the root to
``sys.path``; this conftest does it so tests can ``from pipeline... import``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

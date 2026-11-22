"""Fixtures for the validator tests. Helpers live in ``kg_fixture.py``."""

from __future__ import annotations

from pathlib import Path

import pytest

from kg_fixture import make_kg


@pytest.fixture
def kg(tmp_path: Path) -> Path:
    """A fresh copy of the small valid fixture graph; returns its ``data`` directory."""
    return make_kg(tmp_path)

"""Unit tests for :mod:`pipeline.config`.

Covers the consolidated ``.env.local`` loader + repo-root/state-file helpers
that replaced the three formerly-duplicated loaders in ``pipeline.db``,
``pipeline.sources._http``, and ``pipeline.rerank.cohere``.

Every test re-points ``pipeline.config.ENV_PATH`` / ``PIPELINE_STATE_DIR``
at tmp paths and resets the ``load_env_once._loaded`` latch so we never
touch the real ``.env.local`` on disk.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pipeline import config as cfg


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_loader_latch():
    """Each test starts with a fresh ``load_env_once._loaded`` latch."""
    if hasattr(cfg.load_env_once, "_loaded"):
        delattr(cfg.load_env_once, "_loaded")
    yield
    if hasattr(cfg.load_env_once, "_loaded"):
        delattr(cfg.load_env_once, "_loaded")


def _point_env_at(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, contents: str) -> Path:
    """Point ``cfg.ENV_PATH`` at a tmp file containing ``contents``."""
    fake = tmp_path / ".env.local"
    fake.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(cfg, "ENV_PATH", fake)
    return fake


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #


def test_load_env_once_idempotent(monkeypatch, tmp_path):
    """Repeated calls should re-read the file at most once."""
    fake = _point_env_at(monkeypatch, tmp_path, "SAICA_TEST_KEY=first\n")
    monkeypatch.delenv("SAICA_TEST_KEY", raising=False)

    cfg.load_env_once()
    assert os.environ["SAICA_TEST_KEY"] == "first"

    # Mutate the file and verify the second call is a no-op.
    fake.write_text("SAICA_TEST_KEY=second\n", encoding="utf-8")
    cfg.load_env_once()
    assert os.environ["SAICA_TEST_KEY"] == "first"


def test_load_env_respects_existing_os_environ(monkeypatch, tmp_path):
    """Values already in the environment must not be overridden by the file."""
    _point_env_at(monkeypatch, tmp_path, "SAICA_TEST_KEY=from_file\n")
    monkeypatch.setenv("SAICA_TEST_KEY", "from_env")

    cfg.load_env_once()
    assert os.environ["SAICA_TEST_KEY"] == "from_env"


def test_load_env_parses_quotes_and_skips_comments(monkeypatch, tmp_path):
    """Comment / blank lines are skipped; surrounding quotes are stripped."""
    _point_env_at(
        monkeypatch,
        tmp_path,
        "# header comment\n"
        "\n"
        'SAICA_DOUBLE="with spaces"\n'
        "SAICA_SINGLE='tick-quoted'\n"
        "SAICA_BARE=plain\n"
        "NO_EQUALS_SIGN\n",
    )
    for k in ("SAICA_DOUBLE", "SAICA_SINGLE", "SAICA_BARE", "NO_EQUALS_SIGN"):
        monkeypatch.delenv(k, raising=False)

    cfg.load_env_once()
    assert os.environ["SAICA_DOUBLE"] == "with spaces"
    assert os.environ["SAICA_SINGLE"] == "tick-quoted"
    assert os.environ["SAICA_BARE"] == "plain"
    assert "NO_EQUALS_SIGN" not in os.environ


def test_load_env_handles_missing_file(monkeypatch, tmp_path):
    """A missing .env.local must not raise."""
    monkeypatch.setattr(cfg, "ENV_PATH", tmp_path / "does-not-exist.env")
    cfg.load_env_once()  # must not raise


def test_require_env_returns_value(monkeypatch, tmp_path):
    _point_env_at(monkeypatch, tmp_path, "SAICA_REQUIRED=hello\n")
    monkeypatch.delenv("SAICA_REQUIRED", raising=False)
    assert cfg.require_env("SAICA_REQUIRED") == "hello"


def test_require_env_raises_on_missing(monkeypatch, tmp_path):
    _point_env_at(monkeypatch, tmp_path, "")  # empty file
    monkeypatch.delenv("SAICA_MISSING", raising=False)
    with pytest.raises(RuntimeError, match="SAICA_MISSING not set"):
        cfg.require_env("SAICA_MISSING")


def test_optional_env_returns_default_on_missing(monkeypatch, tmp_path):
    _point_env_at(monkeypatch, tmp_path, "")
    monkeypatch.delenv("SAICA_OPT", raising=False)
    assert cfg.optional_env("SAICA_OPT") is None
    assert cfg.optional_env("SAICA_OPT", "fallback") == "fallback"


def test_state_file_creates_pipeline_state_dir(monkeypatch, tmp_path):
    """``state_file`` must create ``.pipeline/`` lazily on first use."""
    fake_state = tmp_path / ".pipeline"
    assert not fake_state.exists()
    monkeypatch.setattr(cfg, "PIPELINE_STATE_DIR", fake_state)

    p = cfg.state_file("counter.json")
    assert fake_state.is_dir()
    assert p == fake_state / "counter.json"


def test_repo_root_is_a_real_dir():
    """``REPO_ROOT`` must resolve to an actual directory on disk."""
    assert cfg.REPO_ROOT.is_dir()
    # Sanity: the pipeline package should live directly under REPO_ROOT.
    assert (cfg.REPO_ROOT / "pipeline" / "config.py").is_file()


def test_env_path_matches_repo_root_dotenv():
    """``ENV_PATH`` must point at ``<REPO_ROOT>/.env.local`` by default."""
    # Re-import to bypass any per-test monkeypatch of the module attribute.
    import importlib

    fresh = importlib.reload(cfg)
    try:
        assert fresh.ENV_PATH == fresh.REPO_ROOT / ".env.local"
    finally:
        importlib.reload(cfg)

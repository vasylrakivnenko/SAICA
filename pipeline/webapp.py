"""Web entrypoint: the /ask + /assess API, optionally serving the static site.

Wraps :mod:`pipeline.ask.server` without modifying it:

* Maps a hosted OpenAI-compatible provider onto the ``AZURE_KIMI_*`` env vars
  that ``pipeline.extract.kimi.get_client`` reads. Today that is Hyperbolic:
  if ``HYPERBOLIC_API_KEY`` is set and ``AZURE_KIMI_API_KEY`` is not, the
  backend talks to ``https://api.hyperbolic.ai/inference/v1`` using ``ASK_MODEL``
  (default: ``deepseek-v4.1-flash``). Explicit ``AZURE_KIMI_*`` vars always win.
* Builds the semantic-retrieval index (``.cache/embeddings/``) on startup if
  it is missing, so a fresh checkout or deployment works without a manual step.
* Mounts the API under ``/api`` (``/api/ask``, ``/api/assess``,
  ``/api/health``) so the site can call it same-origin.
* With ``SERVE_STATIC=1``, also serves ``site/dist`` at ``/`` — one process,
  one port, for production.

Run::

    python -m pipeline.webapp                      # dev: API on 127.0.0.1:4322
    SERVE_STATIC=1 ASK_HOST=0.0.0.0 ASK_PORT=5000 python -m pipeline.webapp
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("pipeline.webapp")

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIST = REPO_ROOT / "site" / "dist"

HYPERBOLIC_ENDPOINT = "https://api.hyperbolic.ai/inference/v1"
DEFAULT_MODEL = "deepseek-v4.1-flash"


def configure_provider() -> str:
    """Point the backend's OpenAI-compatible client at the configured provider.

    Returns a short human-readable description for the startup log.
    """
    if os.environ.get("AZURE_KIMI_API_KEY"):
        return f"explicit AZURE_KIMI_* config ({os.environ.get('AZURE_KIMI_MODEL', 'Kimi-K2.5')})"
    key = os.environ.get("HYPERBOLIC_API_KEY")
    if not key:
        return "NO LLM KEY — /api/ask will fail until HYPERBOLIC_API_KEY is set"
    model = os.environ.get("ASK_MODEL", DEFAULT_MODEL)
    os.environ["AZURE_KIMI_API_KEY"] = key
    os.environ.setdefault("AZURE_KIMI_ENDPOINT", HYPERBOLIC_ENDPOINT)
    os.environ.setdefault("AZURE_KIMI_MODEL", model)
    return f"Hyperbolic ({os.environ['AZURE_KIMI_MODEL']})"


def ensure_embeddings() -> None:
    """Build the retrieval index if missing or older than the KG data (~10s on CPU)."""
    from pipeline.embeddings.compute import (
        CACHE_DIR,
        DATA_DIR,
        compute_embeddings,
        save_store,
    )

    vectors, meta = CACHE_DIR / "vectors.npy", CACHE_DIR / "meta.json"
    if vectors.exists() and meta.exists():
        built_at = min(vectors.stat().st_mtime, meta.stat().st_mtime)
        newest_data = max(
            (p.stat().st_mtime for p in DATA_DIR.rglob("*.y*ml")), default=0.0
        )
        if newest_data <= built_at:
            return
        log.info("KG data changed since the embeddings index was built; rebuilding")
    log.info("building embeddings index at %s", CACHE_DIR)
    save_store(compute_embeddings())


def build_app():
    from fastapi import FastAPI

    # Import after configure_provider() so the server reads the final env.
    from pipeline.ask.server import app as api_app

    root = FastAPI(title="SAICA-KG")
    root.mount("/api", api_app)

    if os.environ.get("SERVE_STATIC") == "1":
        from fastapi.staticfiles import StaticFiles

        if not SITE_DIST.is_dir():
            raise RuntimeError(
                f"SERVE_STATIC=1 but {SITE_DIST} does not exist; build the site first"
            )
        root.mount("/", StaticFiles(directory=SITE_DIST, html=True), name="site")
    return root


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    provider = configure_provider()
    ensure_embeddings()
    app = build_app()
    host = os.environ.get("ASK_HOST", "127.0.0.1")
    port = int(os.environ.get("ASK_PORT", "4322"))
    log.info(
        "starting on %s:%d — LLM: %s — static site: %s",
        host,
        port,
        provider,
        "on" if os.environ.get("SERVE_STATIC") == "1" else "off",
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

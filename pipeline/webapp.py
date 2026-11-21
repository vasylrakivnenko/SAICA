"""Web entrypoint: the /ask + /assess API, optionally serving the static site.

Wraps :mod:`pipeline.ask.server` without modifying it:

* Maps a hosted OpenAI-compatible provider onto the ``AZURE_KIMI_*`` env vars
  that ``pipeline.extract.kimi.get_client`` reads. Today that is Hyperbolic:
  if ``HYPERBOLIC_API_KEY`` is set and ``AZURE_KIMI_API_KEY`` is not, the
  backend talks to ``https://api.hyperbolic.ai/inference/v1`` using ``ASK_MODEL``
  (default: ``deepseek-v4.1-flash``). Explicit ``AZURE_KIMI_*`` vars always win.
* Prepares semantic retrieval on the first Ask request, not before opening the
  HTTP port. Cold model downloads must not block publishing health checks.
* Mounts the API under ``/api`` (``/api/ask``, ``/api/assess``,
  ``/api/health``) so the site can call it same-origin.
* With ``SERVE_STATIC=1``, also serves ``site/dist`` at ``/`` — one process,
  one port, for production. Every page answers at both ``/x`` and ``/x/``
  with 200 (no slash redirect; pages carry a canonical tag), old underscore
  failure-mode URLs 301 to the hyphenated ones, and ``/x/index.html`` 301s
  to ``/x/``.
* Every response carries nosniff / referrer-policy / x-frame-options, plus
  HSTS on https requests.
* Responses are gzipped; data files (``/api/*``, ``/kit/*``, ``*.json`` …)
  carry ``X-Robots-Tag: noindex`` so they stay fetchable but out of search
  results; hashed ``/_astro/*`` assets are cached for a year.

Run::

    python -m pipeline.webapp                      # dev: API on 127.0.0.1:4322
    SERVE_STATIC=1 ASK_HOST=0.0.0.0 ASK_PORT=5000 python -m pipeline.webapp
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Lock

log = logging.getLogger("pipeline.webapp")

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIST = REPO_ROOT / "site" / "dist"

HYPERBOLIC_ENDPOINT = "https://api.hyperbolic.ai/inference/v1"
DEFAULT_MODEL = "deepseek-v4.1-flash"

# Data files: fetchable (the /graph page reads /api/v1/*.json at runtime, so
# robots.txt must not block them) but kept out of search results.
NOINDEX_PREFIXES = ("/api/", "/kit/")
NOINDEX_SUFFIXES = (".json", ".jsonl", ".pyc", ".py", ".md", ".yml", ".yaml")
# Astro writes content-hashed file names here, so they never change in place.
IMMUTABLE_PREFIX = "/_astro/"
# Baseline hardening on every response. No CSP yet: the pages ship inline
# scripts/styles, so a policy needs nonces or hashes first. HSTS is added only
# for https requests (see SiteHeaders), never on the plain-http dev server.
SECURITY_HEADERS = (
    ("x-content-type-options", "nosniff"),
    ("referrer-policy", "strict-origin-when-cross-origin"),
    ("x-frame-options", "SAMEORIGIN"),
)
HSTS_HEADER = ("strict-transport-security", "max-age=31536000")


def extra_headers(path: str, status: int) -> list[tuple[str, str]]:
    """Headers the site adds to a response for ``path`` (pure; unit-tested)."""
    out: list[tuple[str, str]] = []
    lower = path.lower()
    if (
        path == "/api"
        or lower.startswith(NOINDEX_PREFIXES)
        or lower.endswith(NOINDEX_SUFFIXES)
    ):
        out.append(("x-robots-tag", "noindex"))
    if path.startswith(IMMUTABLE_PREFIX) and status in (200, 304):
        out.append(("cache-control", "public, max-age=31536000, immutable"))
    return out


class SiteHeaders:
    """ASGI middleware that applies :func:`extra_headers` to every HTTP response."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                from starlette.datastructures import MutableHeaders

                headers = MutableHeaders(scope=message)
                for key, value in extra_headers(path, message["status"]):
                    headers[key] = value
                for key, value in SECURITY_HEADERS:
                    headers.setdefault(key, value)
                # scope["scheme"] is "https" behind Replit's TLS proxy because
                # uvicorn runs with proxy_headers=True (see main()).
                if scope.get("scheme") == "https":
                    headers.setdefault(*HSTS_HEADER)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def permanent_redirect(scope, path: str):
    """301 to ``path`` on the same origin, keeping the query string.

    The Location is relative on purpose: the client resolves it against the URL
    it actually requested (https://saica.ai/...), so the redirect stays on the
    https canonical behind Replit's TLS proxy without trusting any forwarded
    header (an absolute URL built from X-Forwarded-* would let a client poison
    a cached 301).
    """
    from starlette.responses import RedirectResponse

    query = scope.get("query_string", b"").decode("latin-1")
    return RedirectResponse(path + (f"?{query}" if query else ""), status_code=301)


def site_files(directory: Path):
    """``StaticFiles(html=True)`` that serves ``/x`` like ``/x/`` instead of redirecting."""
    import os.path
    import stat

    import anyio
    from fastapi.staticfiles import StaticFiles

    class SiteFiles(StaticFiles):
        async def _page(self, path: str):
            """(full_path, stat) of ``<path>/index.html`` if it exists, else None."""
            try:
                full, st = await anyio.to_thread.run_sync(
                    self.lookup_path, os.path.join(path, "index.html")
                )
            except (OSError, ValueError):
                return None
            return (full, st) if st is not None and stat.S_ISREG(st.st_mode) else None

        async def get_response(self, path: str, scope):
            # ``path`` is Starlette's normalised, relative file path ("about",
            # "." for the root). Redirect targets are built from it, never from
            # the raw request path, so "//host/%2e%2e/x" cannot become an
            # off-site "//host/..." Location.
            if scope["method"] in ("GET", "HEAD"):
                rel = path.replace(os.sep, "/")
                # Failure-mode slugs moved from scope_creep to scope-creep.
                if rel.startswith("failure-modes/") and "_" in rel:
                    new_dir = rel.replace("_", "-")
                    # .../scope_creep/index.html -> /failure-modes/scope-creep/
                    if new_dir.endswith("/index.html"):
                        new_dir = new_dir[: -len("/index.html")]
                    if await self._page(new_dir) is not None:
                        return permanent_redirect(scope, f"/{new_dir}/")
                # /x/index.html duplicates /x/: send it to the canonical form.
                if rel == "index.html" or rel.endswith("/index.html"):
                    parent = rel[: -len("index.html")].rstrip("/")
                    if await self._page(parent or ".") is not None:
                        return permanent_redirect(
                            scope, f"/{parent}/" if parent else "/"
                        )
                # /x -> serve x/index.html directly (Starlette would 307 to /x/).
                elif rel != "." and not scope["path"].endswith("/"):
                    page = await self._page(rel)
                    if page is not None:
                        return self.file_response(*page, scope)
            return await super().get_response(path, scope)

    return SiteFiles(directory=directory, html=True)


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
    from pipeline.ask.server import create_app

    retrieval_lock = Lock()
    retrieval_ready = False

    def retrieve(question: str, k: int, *, node_type: str | None = None):
        # Ask handlers run in worker threads. Serialize the initial index/model
        # setup so simultaneous first questions cannot write the same cache.
        nonlocal retrieval_ready
        with retrieval_lock:
            from pipeline.embeddings.query import find_similar

            if not retrieval_ready:
                ensure_embeddings()
            hits = list(find_similar(question, k=k, node_type=node_type))
            retrieval_ready = True
            return hits

    api_app = create_app(find_similar=retrieve)

    root = FastAPI(title="SAICA-KG")
    serve_static = os.environ.get("SERVE_STATIC") == "1"

    if serve_static:
        from fastapi.staticfiles import StaticFiles

        if not SITE_DIST.is_dir():
            raise RuntimeError(
                f"SERVE_STATIC=1 but {SITE_DIST} does not exist; build the site first"
            )
        # Astro prerenders the published graph API (snapshot.json and sibling
        # routes) into site/dist/api/v1. Starlette matches mounts in order, so
        # this must be registered before the dynamic /api mount, which would
        # otherwise swallow every /api/v1/* request and answer 404.
        static_api_v1 = SITE_DIST / "api" / "v1"
        if static_api_v1.is_dir():
            root.mount(
                "/api/v1", StaticFiles(directory=static_api_v1), name="site-api-v1"
            )

    root.mount("/api", api_app)

    if serve_static:
        root.mount("/", site_files(SITE_DIST), name="site")

    from starlette.middleware.gzip import GZipMiddleware

    # Inner -> outer: headers are set on the uncompressed response, then gzip.
    root.add_middleware(SiteHeaders)
    root.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)
    return root


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    provider = configure_provider()
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
    # Behind Replit's TLS proxy: take scheme/client from X-Forwarded-* so any
    # absolute URL the app builds (e.g. FastAPI's slash redirects under /api)
    # says https. The deployment is reachable only through that proxy.
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "*"),
    )


if __name__ == "__main__":
    main()

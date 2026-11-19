"""Publishing startup must not wait for the embedding model or network."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from fastapi.testclient import TestClient

from pipeline import webapp


def test_static_and_health_do_not_initialize_retrieval(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<h1>Catalog</h1>")
    monkeypatch.setenv("SERVE_STATIC", "1")
    monkeypatch.setattr(webapp, "SITE_DIST", tmp_path)
    prepare = Mock(side_effect=AssertionError("startup must not load embeddings"))
    monkeypatch.setattr(webapp, "ensure_embeddings", prepare)

    with TestClient(webapp.build_app()) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/health").json()["ok"] is True
    prepare.assert_not_called()


def _build_site(dist):
    """Minimal Astro-like dist with the prerendered graph API under api/v1."""
    v1 = dist / "api" / "v1"
    (v1 / "catalog").mkdir(parents=True)
    (dist / "index.html").write_text("<h1>Catalog</h1>")
    (dist / "favicon.svg").write_text("<svg/>")
    (v1 / "snapshot.json").write_text('{"nodes": [], "edges": []}')
    (v1 / "catalog" / "tools.json").write_text('{"items": ["semgrep"]}')


def test_static_mode_serves_prerendered_api_v1_before_dynamic_api(monkeypatch, tmp_path):
    _build_site(tmp_path)
    monkeypatch.setenv("SERVE_STATIC", "1")
    monkeypatch.setattr(webapp, "SITE_DIST", tmp_path)

    with TestClient(webapp.build_app()) as client:
        snapshot = client.get("/api/v1/snapshot.json")
        assert snapshot.status_code == 200
        assert snapshot.json() == {"nodes": [], "edges": []}

        nested = client.get("/api/v1/catalog/tools.json")
        assert nested.status_code == 200
        assert nested.json() == {"items": ["semgrep"]}

        assert client.get("/api/v1/missing.json").status_code == 404

        # The dynamic API and the rest of the static site are unaffected.
        assert client.get("/api/health").json()["ok"] is True
        assert client.get("/").status_code == 200
        assert client.get("/favicon.svg").status_code == 200


def test_static_mode_without_api_v1_keeps_dynamic_api(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<h1>Catalog</h1>")
    monkeypatch.setenv("SERVE_STATIC", "1")
    monkeypatch.setattr(webapp, "SITE_DIST", tmp_path)

    with TestClient(webapp.build_app()) as client:
        assert client.get("/api/health").json()["ok"] is True
        assert client.get("/api/v1/snapshot.json").status_code == 404
        assert client.get("/").status_code == 200


def test_static_mode_requires_built_site(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setenv("SERVE_STATIC", "1")
    monkeypatch.setattr(webapp, "SITE_DIST", tmp_path / "missing")

    with pytest.raises(RuntimeError, match="build the site first"):
        webapp.build_app()


def test_api_only_mode_does_not_serve_site_files(monkeypatch, tmp_path):
    _build_site(tmp_path)
    monkeypatch.delenv("SERVE_STATIC", raising=False)
    monkeypatch.setattr(webapp, "SITE_DIST", tmp_path)

    with TestClient(webapp.build_app()) as client:
        assert client.get("/api/health").json()["ok"] is True
        assert client.get("/api/v1/snapshot.json").status_code == 404
        assert client.get("/").status_code == 404


def test_retrieval_prepares_once_and_preserves_filters(monkeypatch):
    from pipeline.ask import server
    from pipeline.embeddings import query

    monkeypatch.delenv("SERVE_STATIC", raising=False)
    prepare = Mock()
    search = Mock(return_value=[("tool-example", 0.9)])
    monkeypatch.setattr(webapp, "ensure_embeddings", prepare)
    monkeypatch.setattr(query, "find_similar", search)
    factory = Mock(wraps=server.create_app)
    monkeypatch.setattr(server, "create_app", factory)
    webapp.build_app()
    retriever = factory.call_args.kwargs["find_similar"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        hits = list(pool.map(lambda _: retriever("question", 3, node_type="tool"), range(2)))
    assert hits == [[("tool-example", 0.9)], [("tool-example", 0.9)]]
    prepare.assert_called_once()
    assert search.call_count == 2
    search.assert_called_with("question", k=3, node_type="tool")


def test_main_opens_server_without_preparing_embeddings(monkeypatch):
    import uvicorn

    monkeypatch.setenv("ASK_HOST", "0.0.0.0")
    monkeypatch.setenv("ASK_PORT", "5000")
    monkeypatch.setattr(webapp, "configure_provider", lambda: "test")
    app = object()
    monkeypatch.setattr(webapp, "build_app", lambda: app)
    prepare = Mock(side_effect=AssertionError("blocking startup work"))
    monkeypatch.setattr(webapp, "ensure_embeddings", prepare)
    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)

    webapp.main()

    prepare.assert_not_called()
    run.assert_called_once_with(app, host="0.0.0.0", port=5000, log_level="info")

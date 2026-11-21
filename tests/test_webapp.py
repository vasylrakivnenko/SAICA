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


def test_static_mode_serves_prerendered_api_v1_before_dynamic_api(
    monkeypatch, tmp_path
):
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
        hits = list(
            pool.map(lambda _: retriever("question", 3, node_type="tool"), range(2))
        )
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
    run.assert_called_once_with(
        app,
        host="0.0.0.0",
        port=5000,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


# --- static-site serving for search engines (trailing slash, gzip, headers) ---

PAGE = (
    "<!doctype html><title>About</title>"
    + "<p>SAICA-Bench measures detectors.</p>" * 40
)


def _seo_site(dist):
    (dist / "about").mkdir()
    (dist / "about" / "index.html").write_text(PAGE)
    (dist / "index.html").write_text("<h1>Home</h1>")
    (dist / "404.html").write_text("<h1>Page not found</h1>")
    (dist / "failure-modes" / "scope-creep").mkdir(parents=True)
    (dist / "failure-modes" / "scope-creep" / "index.html").write_text(
        "<h1>Scope creep</h1>"
    )
    (dist / "bench").mkdir()
    (dist / "bench" / "results.json").write_text('{"modes": []}')
    (dist / "kit").mkdir()
    (dist / "kit" / "saica_check.py").write_text("print('hi')\n")
    (dist / "_astro").mkdir()
    (dist / "_astro" / "app.AbC123.js").write_text("console.log(1)")
    (dist / "api" / "v1").mkdir(parents=True)
    (dist / "api" / "v1" / "snapshot.json").write_text('{"nodes": []}')


def _seo_client(monkeypatch, tmp_path):
    _seo_site(tmp_path)
    monkeypatch.setenv("SERVE_STATIC", "1")
    monkeypatch.setattr(webapp, "SITE_DIST", tmp_path)
    return TestClient(webapp.build_app(), follow_redirects=False)


def test_pages_answer_with_and_without_trailing_slash(monkeypatch, tmp_path):
    with _seo_client(monkeypatch, tmp_path) as client:
        bare, slashed = client.get("/about"), client.get("/about/")
        assert bare.status_code == slashed.status_code == 200
        assert bare.text == slashed.text == PAGE
        assert client.head("/about").status_code == 200
        assert client.get("/").text == "<h1>Home</h1>"
        # Plain files still resolve normally.
        assert client.get("/bench/results.json").json() == {"modes": []}


def test_index_html_and_old_slugs_redirect_permanently(monkeypatch, tmp_path):
    with _seo_client(monkeypatch, tmp_path) as client:
        r = client.get("/about/index.html")
        assert (r.status_code, r.headers["location"]) == (301, "/about/")
        r = client.get("/index.html")
        assert (r.status_code, r.headers["location"]) == (301, "/")
        for old in ("/failure-modes/scope_creep/", "/failure-modes/scope_creep"):
            r = client.get(old)
            assert (r.status_code, r.headers["location"]) == (
                301,
                "/failure-modes/scope-creep/",
            )
        r = client.get("/failure-modes/scope_creep/?ref=x")
        assert r.headers["location"] == "/failure-modes/scope-creep/?ref=x"
        # An underscore slug with no hyphenated page is a plain 404.
        assert client.get("/failure-modes/not_a_mode/").status_code == 404


def test_redirect_target_cannot_leave_the_site(monkeypatch, tmp_path):
    with _seo_client(monkeypatch, tmp_path) as client:
        r = client.get("http://testserver//evil.example/%2e%2e/about/index.html")
        assert r.status_code == 301
        assert r.headers["location"] == "/about/"
        assert client.get("/%2e%2e/about/index.html").status_code == 404


def test_unknown_path_serves_404_page(monkeypatch, tmp_path):
    with _seo_client(monkeypatch, tmp_path) as client:
        r = client.get("/no-such-page/")
        assert r.status_code == 404
        assert "Page not found" in r.text
        assert client.get("/no-such-page").status_code == 404


def test_data_files_are_noindex_but_fetchable(monkeypatch, tmp_path):
    with _seo_client(monkeypatch, tmp_path) as client:
        for path in (
            "/api/v1/snapshot.json",
            "/api/health",
            "/bench/results.json",
            "/kit/saica_check.py",
        ):
            r = client.get(path)
            assert r.status_code == 200, path
            assert r.headers["x-robots-tag"] == "noindex", path
        for path in ("/", "/about", "/about/", "/no-such-page/"):
            assert "x-robots-tag" not in client.get(path).headers, path


def test_gzip_and_asset_cache_headers(monkeypatch, tmp_path):
    with _seo_client(monkeypatch, tmp_path) as client:
        r = client.get("/about/", headers={"Accept-Encoding": "gzip"})
        assert r.headers["content-encoding"] == "gzip"
        assert r.text == PAGE  # httpx decodes transparently
        r = client.get("/about/", headers={"Accept-Encoding": "identity"})
        assert "content-encoding" not in r.headers
        r = client.get("/_astro/app.AbC123.js")
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert "immutable" not in client.get("/_astro/missing.js").headers.get(
            "cache-control", ""
        )
        assert "immutable" not in client.get("/about/").headers.get("cache-control", "")


def test_extra_headers_rules():
    noindex = ("x-robots-tag", "noindex")
    assert noindex in webapp.extra_headers("/api/ask", 200)
    assert noindex in webapp.extra_headers("/kit/prompts/scope_creep.md", 200)
    assert noindex in webapp.extra_headers("/kit/saica-ci.yml", 200)
    assert noindex in webapp.extra_headers("/kit/__pycache__/x.cpython-312.pyc", 200)
    assert noindex in webapp.extra_headers("/kit/events.sample.jsonl", 200)
    assert noindex in webapp.extra_headers("/embeddings.json", 200)
    assert webapp.extra_headers("/failure-modes/scope-creep/", 200) == []
    assert webapp.extra_headers("/llms.txt", 200) == []
    assert webapp.extra_headers("/og.png", 200) == []

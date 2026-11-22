"""The static-host files of the site say what the Python server does.

The site can be served by ``pipeline.webapp`` (``SERVE_STATIC=1``) or by a static host. For Cloudflare Pages
the response headers and the old-URL redirects live in ``site/public/_headers`` and ``site/public/_redirects``.
These tests fail when those files and ``pipeline/webapp.py`` / ``data/failure_modes/`` drift apart.
"""

from __future__ import annotations

from pathlib import Path

from pipeline import webapp

REPO = Path(__file__).resolve().parents[1]
HEADERS = REPO / "site" / "public" / "_headers"
REDIRECTS = REPO / "site" / "public" / "_redirects"


def parse_headers(text: str) -> dict[str, dict[str, str]]:
    """``{pattern: {lower-case header name: value}}`` from a Cloudflare Pages ``_headers`` file."""
    rules: dict[str, dict[str, str]] = {}
    current = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            current = line.strip()
            assert current not in rules, f"pattern listed twice: {current}"
            rules[current] = {}
        else:
            assert current is not None, f"header line before any pattern: {line!r}"
            name, _, value = line.strip().partition(":")
            rules[current][name.strip().lower()] = value.strip()
    return rules


def parse_redirects(text: str) -> list[tuple[str, str, str]]:
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split()
        assert len(parts) == 3, f"expected 'source destination code': {line!r}"
        rows.append((parts[0], parts[1], parts[2]))
    return rows


def test_headers_file_fits_cloudflare_limits():
    text = HEADERS.read_text(encoding="utf-8")
    rules = parse_headers(text)
    assert len(rules) <= 100
    assert all(len(line) <= 2000 for line in text.splitlines())
    for pattern, headers in rules.items():
        assert pattern.startswith("/"), pattern
        assert pattern.count("*") <= 1, f"one splat per pattern: {pattern}"
        assert headers, f"pattern without headers: {pattern}"


def test_security_headers_match_the_server():
    every = parse_headers(HEADERS.read_text(encoding="utf-8"))["/*"]
    expected = dict(webapp.SECURITY_HEADERS)
    expected[webapp.HSTS_HEADER[0]] = webapp.HSTS_HEADER[1]
    assert every == expected


def test_noindex_and_cache_rules_match_the_server():
    rules = parse_headers(HEADERS.read_text(encoding="utf-8"))
    noindex = {p for p, h in rules.items() if h.get("x-robots-tag") == "noindex"}
    # .pyc is in the server's list as a safeguard; no such file is published.
    suffixes = {s for s in webapp.NOINDEX_SUFFIXES if s != ".pyc"}
    expected = {f"{prefix}*" for prefix in webapp.NOINDEX_PREFIXES} | {
        f"/*{suffix}" for suffix in suffixes
    }
    assert noindex == expected
    cache = {p: h["cache-control"] for p, h in rules.items() if "cache-control" in h}
    assert cache == {
        f"{webapp.IMMUTABLE_PREFIX}*": "public, max-age=31536000, immutable"
    }
    # The same answers from the server's own function, for one path of each kind.
    assert ("x-robots-tag", "noindex") in webapp.extra_headers(
        "/api/v1/snapshot.json", 200
    )
    assert ("cache-control", cache["/_astro/*"]) in webapp.extra_headers(
        "/_astro/x.css", 200
    )


def test_every_underscore_failure_mode_is_redirected_to_its_hyphen_page():
    rows = parse_redirects(REDIRECTS.read_text(encoding="utf-8"))
    assert len(rows) <= 2000
    assert len({source for source, _, _ in rows}) == len(
        rows
    ), "a source is listed twice"
    ids = sorted(p.stem for p in (REPO / "data" / "failure_modes").glob("*.yml"))
    expected = set()
    for fm in (i for i in ids if "_" in i):
        target = f"/failure-modes/{fm.replace('_', '-')}/"
        expected.add((f"/failure-modes/{fm}", target, "301"))
        expected.add((f"/failure-modes/{fm}/", target, "301"))
    assert set(rows) == expected
    assert all(source != target for source, target, _ in rows)

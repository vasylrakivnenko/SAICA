#!/usr/bin/env bash
# Check that a deployment serves the pages and files the project links to.
#
# Usage:
#   bash scripts/smoke_check.sh https://saica.ai
#   bash scripts/smoke_check.sh http://localhost:5000 --no-api
#
# It sends one GET per URL below and reads the answer; it changes nothing.
# Exit 0 when every required check passes, 1 otherwise.
# `--no-api` skips /api/health: use it for a static host (Cloudflare Pages) or a static preview, which
# have no backend.
#
# Run it after every deploy and before pushing a README that links to new
# pages (review 2026-11-21, D2: push and redeploy are order-sensitive).
set -u

base="${1:-}"
if [ -z "$base" ] || [ "$base" = "-h" ] || [ "$base" = "--help" ]; then
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi
base="${base%/}"
with_api=1
[ "${2:-}" = "--no-api" ] && with_api=0

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
failed=0

# check <path> <text that must be in the body, or ""> <label>
check() {
  local path="$1" needle="$2" label="$3" code
  code="$(curl -sS -L --max-time 30 -A "saica-smoke-check" -o "$tmp" -w '%{http_code}' "$base$path" 2>/dev/null)" || code="000"
  if [ "$code" != "200" ]; then
    echo "FAIL  $path  -> HTTP $code  ($label)"
    failed=$((failed + 1))
  elif [ -n "$needle" ] && ! grep -q -- "$needle" "$tmp"; then
    echo "FAIL  $path  -> 200, but the body has no \"$needle\"  ($label)"
    failed=$((failed + 1))
  else
    echo "ok    $path  ($label)"
  fi
}

check "/"                              "SAICA-Bench"  "home page is the benchmark, not the old site"
check "/findings/"                     ""             "findings"
check "/benchmark/"                    ""             "method and per-mode setup"
check "/failure-modes/"                ""             "failure-mode hub"
check "/failure-modes/scope-creep/"    ""             "one failure-mode page (hyphen URL)"
check "/tools/"                        ""             "tool catalog"
check "/tool-coverage/"                ""             "kit builder"
check "/bench/results.json"            '"version"'    "published results, with a version"
check "/api/v1/snapshot.json"          '"tools"'      "catalog snapshot"
check "/llms.txt"                      "SAICA-Bench"  "llms.txt"
check "/sitemap.xml"                   "<loc>"        "sitemap"
check "/robots.txt"                    "Sitemap:"     "robots.txt names the sitemap"
if [ "$with_api" -eq 1 ]; then
  check "/api/health"                  ""             "Ask / Assess backend"
fi

# header <path> <header name> <text its value must contain> <label>
header() {
  local path="$1" name="$2" needle="$3" label="$4" value
  value="$(curl -sS --max-time 30 -A "saica-smoke-check" -o /dev/null -D - "$base$path" 2>/dev/null \
    | tr -d '\r' | grep -i "^$name:" | head -1 | cut -d: -f2- | sed 's/^ *//')"
  if printf '%s' "$value" | grep -qi -- "$needle"; then
    echo "ok    $path  $name: $value  ($label)"
  else
    echo "FAIL  $path  $name: ${value:-<not sent>}, expected \"$needle\"  ($label)"
    failed=$((failed + 1))
  fi
}

# The same headers on either host: pipeline/webapp.py sets them when it serves the site, and
# site/public/_headers sets them on Cloudflare Pages.
header "/"                      "x-content-type-options" "nosniff"  "baseline header on pages"
header "/api/v1/snapshot.json"  "x-robots-tag"           "noindex"  "data files stay out of search results"

# An old underscore URL must answer with a permanent redirect to the hyphen URL
# (pipeline/webapp.py, or site/public/_redirects on Cloudflare Pages).
old="/failure-modes/scope_creep/"
answer="$(curl -sS --max-time 30 -A "saica-smoke-check" -o /dev/null -w '%{http_code} %{redirect_url}' "$base$old" 2>/dev/null)" || answer="000 "
case "$answer" in
  30[18]\ */failure-modes/scope-creep/) echo "ok    $old  -> ${answer%% *} ${answer#* }  (old underscore URL)" ;;
  *) echo "FAIL  $old  -> HTTP ${answer%% *} ${answer#* }  (old underscore URL should redirect to /failure-modes/scope-creep/)"
     failed=$((failed + 1)) ;;
esac

if [ "$failed" -gt 0 ]; then
  echo "$failed check(s) failed for $base"
  exit 1
fi
echo "all required checks passed for $base"

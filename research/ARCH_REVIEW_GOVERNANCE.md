# Architecture Review — Data Integrity & Governance

## Verdict (<=150 words)

SAICA-KG has solid *structural* integrity at the node and cross-node level: Pydantic is the single source of truth (`pipeline/models.py`), and `validator/cli.py::cross_invariants` catches most schema and referential bugs. But governance enforcement is almost entirely **policy-on-paper**. `EDITORIAL_POLICY.md` describes COI disclosure, review cadence, the RFC process, and deletion discipline, yet the only `.github/` asset is an inactive star-refresh scaffold. No CI runs `validator/cli.py` on PRs; no PR template; no id-immutability guard; no crosswalk-category validator; no structured provenance in graduated YAMLs; no real `kg_version` pinning; no taxonomy-version drift alarm. At 38 tools the manual substitute works; at 100+ each gap compounds. The single highest-leverage fix is **CI-enforced validation on PRs** — every other mitigation can be attacked from there.

## Strengths

- **Pydantic single-source-of-truth** (`pipeline/models.py:130-426`), chain `schema/*.json` -> `site/src/lib/types.generated.ts`. Site `build` script runs `gen-types` (`site/package.json:9`), so drift is structurally prevented — if `npm run build` runs.
- **Cross-node invariants** in `validator/cli.py:159-244` catch dangling paper refs, unknown FM ids, missing compose_with, broken/cyclic supersedes, under-covered modes, asymmetric composes_with, and 365d staleness.
- **Graduation is human-gated**: `pipeline/cli/graduate.py` forbids LLM writes to `data/`; low-confidence fields become `# REVIEW REQUIRED`.
- **Layered dedup**: `pipeline/dedup.py` indexes YAML + candidates + in-batch URLs with canonical-URL, fuzzy-name, and org/repo-alias rules.
- **Star refresh** is idempotent, round-trip safe (`validator/fetch_github_stars.py`).
- **Crosswalks carry authorship** (`authored_by` + `last_reviewed`).

## Risks and proposals

### Risk 1: No CI gate on PRs
**Severity**: high. A PR adding a dangling `cited_in: [nonexistent-paper]` breaks no hook and no check. Only `.github/workflows/refresh-stars.yml` exists, and its `schedule:` block is commented out (lines 22-25); there is no `pull_request` trigger anywhere. `CONTRIBUTING.md:16` relies on the honor system. **Proposal (S):** `.github/workflows/validate.yml` on `pull_request` + push: `validator/cli.py --strict`, `npm --prefix site run gen-types` (clean-diff), pytest. Half-day; unblocks everything else.

### Risk 2: Citation stability is an honor system
**Severity**: high. `pipeline/models.py:136` enforces the id *pattern*, not immutability. Renaming `data/tools/aider.yml` or editing its `id:` passes validation; external citations to `aider` break. No test, hook, or diff guard. **Proposal (M):** commit `data/manifest.lock.json` = `{kind, id} -> sha256(filename)` frozen at v1.0; CI fails if a locked id disappears (growth is free).

### Risk 3: `kg_version` does not actually let consumers pin
**Severity**: med. `site/src/lib/data.ts:19` hardcodes `DATA_VERSION = '2026.04'`; `kgLastUpdated` is `new Date().toISOString()` at build time (line 230). Nothing archives `snapshot-2026.04.json` or couples the version string to a git tag or content hash. **Proposal (M):** publish immutable `snapshot-YYYY.MM.json` on GitHub Releases; add `content_hash` to the live snapshot; read version from a committed `VERSION`.

### Risk 4: Crosswalk `external_id` not validated against the taxonomy
**Severity**: med. `validator/cli.py:170-179` checks taxonomy *existence* but not category existence; a mapping citing `ASI11` (OWASP goes to `ASI10`) passes. Standalone `Crosswalk` nodes get no cross-check at all — there is no loop over `crosswalks` in `cross_invariants`. **Proposal (S):** build `taxonomy_external_ids: dict[str, set[str]]` from `taxonomies[].categories[].external_id`; assert each `external_id` resolves for both `FailureModeCrosswalk` and `CrosswalkMapping`. ~30 LOC.

### Risk 5: Graduated YAMLs lose structured provenance
**Severity**: med. The graduation header is a YAML *start comment* (`graduate.py:404-410`) — lossy across reformat/round-trip. All 38 current `data/tools/*.yml` (sampled `aider.yml`, `guardrails-ai.yml`) were hand-authored and carry *no* source trace; `Tool` has no `provenance` field (`models.py:130-213`). **Proposal (M):** optional `Provenance` sub-model on Tool / Paper `{source, candidate_id, extractor, overall_confidence, reviewer, graduated_on}`, populated by `graduate.py` as structured YAML; backfill 38 tools with `{source: "hand-authored", reviewer: "vasyl"}`.

### Risk 6: No PR-time duplicate check
**Severity**: med. `DupChecker` runs only inside the Postgres ingestion path (`pipeline/bulk.py:473`), never on a PR that bypasses candidates. Two simultaneous PRs could each add `guardrails-ai` with different ids. **Proposal (S):** `validator/check_duplicates.py` wrapping `DupChecker` over YAML; wire into CI.

### Risk 7: Foreign-taxonomy version drift
**Severity**: med. When OWASP 2027 ships, `data/taxonomies/owasp-agentic-top-10-2026.yml` stays pinned and `owasp-to-saica.yml` may silently point at renumbered codes. `Taxonomy` has no `next_review_due` (`pipeline/models.py:325-359`). **Proposal (M):** add `next_review_due`, warn when overdue, document "new version = new taxonomy node + new crosswalk; old deprecated, never edited in place."

### Risk 8: Citation counts frozen at ingest
**Severity**: low. `Paper.citation_count` (`models.py:292`) is one-shot; `semantic_scholar_id` (line 288) is the hook, but no refresher exists. **Proposal (S):** `validator/refresh_s2_citations.py` mirroring `fetch_github_stars.py`.

### Risk 9: Silent deletion not guarded; no `supersedes` requirement
**Severity**: med. `EDITORIAL_POLICY.md:69` promises "never silently deleted" and an `abandoned -> supersedes` pointer, but neither is enforced. **Proposal (S):** manifest lock from Risk 2 catches deletions; add `if maturity_status=="abandoned" and not supersedes: warn` — six lines.

### Risk 10: Non-ASCII names yield degenerate slugs
**Severity**: low. `pipeline/nlp/pipeline.py:63` strips non-ASCII (`re.sub(r"[^A-Za-z0-9]+", "-", ...)`); a Chinese repo collapses to `---`. Paper-id fallback (lines 82-86) has the same flaw. **Proposal (S):** NFKD + ASCII-ignore pre-pass with `candidate-<db-id>` fallback.

### Risk 11: `snapshot.json` omits git sha and flattened crosswalks
**Severity**: low. `site/src/pages/api/v1/snapshot.json.ts:5-22` dumps all five node kinds — complete. Missing: `kg_commit_sha`, `schema_version`, and a flat `failure_mode_crosswalks` array (currently nested inside `failureModes[].crosswalks`). **Proposal (S):** extend the endpoint.

## Governance enforcement audit

| Policy (`EDITORIAL_POLICY.md`) | Enforced? | How / not how |
|---|---|---|
| `id` immutable once merged (line 50) | No | Pattern only; no manifest lock. |
| Partition enums stable across minor versions (line 52) | Partial | Pydantic enum is the lock; no CHANGELOG enforces "minor". |
| Schema renames require RFC + 30d (line 54) | No | No RFC automation; no PR template. |
| `kg_version` pins (line 55) | No | TS constant in `data.ts:19`; no artifacts. |
| COI disclosure in PR (line 43) | No | No `PULL_REQUEST_TEMPLATE.md`. |
| Maintainer recusal in merge commit (line 44) | No | Honor system; no CODEOWNERS. |
| Review cadence / auto-flag `at_risk` (line 30-33) | Partial | 365d flagged (`cli.py:202-217`); no 30d/180d. |
| Nodes never silently deleted (line 69) | No | No manifest lock, no CI. |
| `supersedes` when abandoned (line 69) | No | Not asserted anywhere. |
| Validator runs on every PR | No | Only `refresh-stars.yml`; no `pull_request`. |
| Advisory-board public (line 73) | N/A | No `MAINTAINERS.yml`. |

## Referential integrity coverage

| Cross-node link | Validator catches? | Notes |
|---|---|---|
| `Tool.cited_in` -> Paper | Yes | `cli.py:187-189`. |
| `Tool.documented_in` -> Paper | Yes | Same loop. |
| `Tool.evaluated_on` -> Paper | **No** | Omitted from the loop. |
| `Tool.addresses_failure_modes` -> FM | Yes | `cli.py:190-192`. |
| `Tool.composes_with` -> Tool + symmetry | Yes | `cli.py:193-196, 219-224`. |
| `Tool.feeds_into` -> Tool | **No** | Not checked. |
| `Tool.supersedes` + cycle | Yes | `cli.py:197-200, 226-227`. |
| `Tool.published_by` -> Org | **No** | No Org node type; free-form string. |
| `FM.prior_work` -> Paper | Yes | `cli.py:170-173`. |
| `FM.canonical_definition_source` -> Paper | **No** | Not checked. |
| `FM.crosswalks[].taxonomy` -> Taxonomy | Yes | `cli.py:174-179`. |
| `FM.crosswalks[].external_id` -> category | **No** | See Risk 4. |
| `Crosswalk.taxonomy` -> Taxonomy | **No** | Standalone Crosswalk node type not cross-checked at all. |
| `Crosswalk.mappings[].saica_value` -> FM | **No** | Not checked. |
| `Crosswalk.mappings[].external_id` -> category | **No** | Not checked. |
| `Taxonomy.paper_id` -> Paper | **No** | Not checked. |
| `FM.related_modes` -> FM | **No** | Not checked. |

Roughly half the referential edges are validated. The standalone `Crosswalk` type (six files) gets per-node validation only.

## Provenance in YAMLs

| What's there | What's missing | Recommendation |
|---|---|---|
| Crosswalks have `authored_by` + `last_reviewed` (`owasp-to-saica.yml:4-6`). | Tools have no author/reviewer/source fields. | Optional `Provenance` sub-model (Risk 5). |
| `Tool` has free-text `contributors`, `editorial_notes`, `inclusion_rationale` (`models.py:211-213`). | All three unpopulated in 38 sampled tools. | Require `inclusion_rationale` on new merges. |
| Graduated YAMLs *would* carry start-comment provenance (`graduate.py:404-410`). | Comments are lossy; no current YAML carries it. | Structured `provenance:` field. |
| Papers have `semantic_scholar_id`. | `citation_count_updated_at` missing. | Add alongside Risk 8. |

## Quick wins

- CI workflow on `pull_request` + push (Risk 1). Unblocks everything.
- `.github/PULL_REQUEST_TEMPLATE.md` with inclusion-rationale + COI + source-URL sections (`CONTRIBUTING.md:17`).
- Extend `cross_invariants` for `Tool.evaluated_on`, `Tool.feeds_into`, `FM.canonical_definition_source`, full `Crosswalk` checks, category-existence (Risk 4). ~40 LOC.
- `abandoned` -> `supersedes` warning (Risk 9). Six lines.
- `validator/check_duplicates.py` wrapping `DupChecker` over YAML (Risk 6).
- NFKD-safe slug in `pipeline/nlp/pipeline.py:63` (Risk 10).

## Medium effort

- `data/manifest.lock.json` + CI diff guard (Risks 2, 9).
- Structured `Provenance` sub-model; backfill 38 tools (Risk 5).
- `validator/refresh_s2_citations.py` + inactive workflow (Risk 8).
- `Taxonomy.next_review_due` + overdue warning + policy docs (Risk 7).
- `VERSION` file + immutable `snapshot-YYYY.MM.json` release artifact + `content_hash` (Risk 3).

## Strategic

- **CODEOWNERS + `MAINTAINERS.yml`** node type with COI flags; auto-block self-merges of own-org tools. Materializes `EDITORIAL_POLICY.md:36-46`.
- **Append-only merge-decision log** in-repo: one line per merge `{pr, decision, reviewer, coi_flagged, rfc_link}`. Delivers on `EDITORIAL_POLICY.md:72-73` in an externally auditable form.
- **RFC mechanization**: model RFCs as a node type (`data/rfcs/*.yml`: `id`, `status`, `opened_on`, `closes_on`, `affects`, `approvals`). Validator refuses schema changes without a closed, approved RFC — only way the 30-day-comment clause survives maintainer rotation.
- **Fork-friendliness**: BibTeX + JSON-LD at `/api/v1/snapshot.{bib,jsonld}` with `content_hash`. Makes the KG genuinely citable from outside the website — the stated mission.

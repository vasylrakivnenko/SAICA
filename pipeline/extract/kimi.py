"""Azure AI Foundry Kimi-K2.5 extraction wrapper.

Backend is the **OpenAI-compatible** endpoint, NOT ``AzureOpenAI``. Endpoint
shape is ``https://<resource>.services.ai.azure.com/openai/v1/``.

Hard constraints baked in here:

- ``max_tokens >= 2048`` always. We default to 4096 so the think-trace has
  budget to spare; below 2048, the content comes back ``None``.
- Concurrency is capped at 3 (vendor max is 8; we leave headroom).
- Retries 429 / transient failures up to 3 times with exponential backoff.
- Structured output is enforced via OpenAI's tool-use pattern:
  ``tools=[{type:function, function:{name, parameters: <json-schema>}}]``
  + ``tool_choice={type:function, function:{name}}``.

Nothing here ever writes YAML. The CLI graduation step is the only path
into ``data/``. These extractions sit in Postgres until a reviewer looks.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from pipeline.cost_caps import CallBudget
from pipeline.extract.schemas import PaperExtraction, ToolExtraction

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_REQUIRED_ENV = ("AZURE_KIMI_API_KEY", "AZURE_KIMI_ENDPOINT")
DEFAULT_MODEL = "Kimi-K2.5"

MAX_CONCURRENCY = 3          # leave 5 vendor-headroom
MAX_TOKENS_DEFAULT = 4096    # must be >= 2048 for this model
MAX_RETRIES = 3              # attempts on 429 / transient network errors
BASE_BACKOFF_SECONDS = 2.0   # 2, 4, 8 ... plus jitter
MAX_RETRY_AFTER_SECONDS = 120.0  # cap for server-specified Retry-After

_concurrency_sem = threading.BoundedSemaphore(MAX_CONCURRENCY)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Failure-mode reference block — hardcoded one-liners so prompt building
# doesn't require a DB or filesystem round-trip. These mirror the
# ``description`` fields in ``data/failure_modes/*.yml`` but compressed to a
# single sentence plus synonym hints. If a new failure mode lands in
# ``pipeline.models.FailureModeId``, update this dict in the same PR.
# ---------------------------------------------------------------------------

FAILURE_MODE_DEFINITIONS: dict[str, str] = {
    "fabrication": (
        "References to APIs/packages/symbols that do NOT exist anywhere — "
        "syntactically plausible, factually false. Synonyms: api-hallucination, "
        "package-hallucination, hallucinated imports."
    ),
    "obsolescence": (
        "References to real APIs/packages that have been deprecated, removed, "
        "or materially changed in their recommended version. Synonyms: "
        "deprecated APIs, outdated library versions, retired endpoints."
    ),
    "dependency_blindness": (
        "Reimplementing from scratch a function/class whose equivalent already "
        "exists in declared dependencies, stdlib, or reachable internal modules. "
        "Synonyms: NIH syndrome, reinvention, reinventing-the-wheel."
    ),
    "logic_error": (
        "Uses real/current APIs correctly at the signature level but encodes "
        "incorrect logic for the task — 'passes type-check, fails correctness'. "
        "Synonyms: semantic bug, incorrect implementation, wrong algorithm."
    ),
    "security_vulnerability": (
        "Introduces injection primitives, weak cryptography, leaked secrets, "
        "insecure deserialization, or analogous security flaws. Synonyms: "
        "insecure code, CWE patterns, SQLi/XSS/RCE, secret leakage."
    ),
    "scope_creep": (
        "Actions outside the user-stated task scope — unrequested file edits, "
        "unasked-for installs, config changes beyond the declared surface, "
        "unprompted follow-on work. Synonyms: out-of-scope edits, over-reach."
    ),
    "context_pollution": (
        "In-session context degrades — relevant prior info dropped, irrelevant "
        "material accumulated, earlier hallucinations treated as ground truth. "
        "Synonyms: trajectory drift, hallucination spiral, context-window overflow, "
        "memory poisoning."
    ),
    "supply_chain_attack": (
        "Induced (by hallucination, adversarial naming, or compromised upstream) "
        "to install or invoke malicious code. Synonyms: slopsquatting, "
        "typosquatting, compromised MCP server, malicious package."
    ),
    "cascading_failure": (
        "Recovery attempts that compound the original error — each fix "
        "introduces NEW errors and repeated iterations spiral further from the "
        "working state. Synonyms: recovery-spiral, compound-error, "
        "error-cascade, fix-regression."
    ),
    "incomplete_execution": (
        "Agent claims completion while subtasks are skipped, stubbed, or "
        "silently dropped — TODOs / `pass` / `NotImplementedError` left behind, "
        "partial implementations declared done, premature termination. "
        "Synonyms: premature-completion, false-completion, partial-completion, "
        "stub-left-behind."
    ),
    "test_manipulation": (
        "Agent games its own evaluation — edits tests or the test harness so "
        "failures disappear without fixing the underlying bug (weakened "
        "asserts, commented-out tests, `pytest.mark.skip`, disabled CI). "
        "Synonyms: silent-workaround, evaluation-gaming, reward-hacking, "
        "test-gaming, spec-gaming."
    ),
}


def _render_failure_mode_reference() -> str:
    lines = [
        "## FailureMode reference (the 11 canonical ids, verbatim)",
        "",
    ]
    for fm_id, defn in FAILURE_MODE_DEFINITIONS.items():
        lines.append(f"- `{fm_id}`: {defn}")
    return "\n".join(lines)


SYSTEM_PROMPT = """\
You are an extraction assistant for SAICA-KG, a curated knowledge graph of
software tools that supervise AI coding agents. Your job is to read one
candidate (a URL plus some metadata / README text / abstract) and emit a
STRUCTURED extraction matching the provided function schema.

## SAICA-KG taxonomy (controlled vocabularies — do NOT invent values)

- ControlParadigm (exactly one, or null): prevention, detection, correction, recovery.
- TemporalPhase (exactly one, or null): pre_generation, in_generation, post_generation.
- AutonomyLevel (exactly one, or null): fully_autonomous, graduated_hitl, full_hitl.
- FailureModeId (multi-valued, subset): fabrication, obsolescence,
  dependency_blindness, logic_error, security_vulnerability, scope_creep,
  context_pollution, supply_chain_attack, cascading_failure,
  incomplete_execution, test_manipulation.
- LocusOfControl (multi-valued, subset): model, prompt, context,
  environment, human.

{failure_mode_reference}

## Failure-mode mapping procedure (read BEFORE filling addresses_failure_modes)

For every candidate tool, walk the 11 ids above and ask:
**"Which of these 11 failure modes does this supervision tool credibly
address?"** Only include ids the README/description supports with direct
language — exact synonyms (e.g. "hallucination" → fabrication,
"slopsquatting" → supply_chain_attack, "deprecated API" → obsolescence,
"reward hacking" → test_manipulation, "premature completion" →
incomplete_execution, "recovery spiral" → cascading_failure) count as
direct evidence; vague marketing ("safer AI", "trustworthy code") does
NOT.

- If the tool is a general-purpose AI coding agent rather than a supervisor
  of one, return an empty list. Do NOT guess.
- For each id you DO include, the ``evidence`` list must contain at least
  one direct quote that names the failure mode or a listed synonym.
- Empty list with confidence ~0.5 is the correct answer when the tool is
  clearly supervision-adjacent but doesn't target any of the 11 ids — this
  is strictly preferred over a speculative assignment.
- Confidence calibration:
    * 0.85-0.95 — README uses the exact id or a canonical synonym
      ("hallucination", "slopsquatting", "deprecated", "injection", etc.).
    * 0.60-0.80 — strong paraphrase with unambiguous framing.
    * 0.40-0.55 — inferred from adjacent language; prefer the empty-list path.
    * <0.40     — return empty list with confidence 0.5.

## Honest MECE frame

The three core facets (ControlParadigm × TemporalPhase × AutonomyLevel) are
intended to be mutually exclusive and collectively exhaustive. Every real
tool lives in exactly ONE cell of that 4×3×3 cube. If the source does not
make the cell unambiguous, return null with low confidence — do NOT guess.

## Confidence + evidence rules

For each field you emit a triple: value, confidence (0-1), evidence (list
of direct quotes from the source). "Prefer null-with-low-confidence over
guessing" is a hard rule. Humans will review anything below 0.7.

- If the source material is silent on a facet, return value=null,
  confidence <= 0.3, evidence=[].
- If you can cite specific text that supports a value, set confidence
  proportional to how unambiguous that text is, and include the quote in
  evidence.
- Never fabricate a repository_url, DOI, or arxiv_id.
- proposed_id should be a kebab-case slug (lowercased, hyphen-separated,
  no leading/trailing hyphens), ideally matching the GitHub repo name.

## Output

You MUST call the function provided by the tool_choice parameter with the
structured payload. Do not return free-form text.
""".format(failure_mode_reference=_render_failure_mode_reference())


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def _check_env() -> None:
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            "Azure Kimi env not configured. Missing: "
            + ", ".join(missing)
            + ". See .env.local for expected values:\n"
            "  AZURE_KIMI_API_KEY=<project key>\n"
            "  AZURE_KIMI_ENDPOINT=https://<resource>.services.ai.azure.com/openai/v1/\n"
            "  AZURE_KIMI_MODEL=Kimi-K2.5\n"
        )


def get_client():
    """Build an OpenAI client pointed at the Kimi-on-Azure endpoint.

    Raises a clear ``RuntimeError`` if env vars are missing. The OpenAI SDK
    is imported lazily so the module import doesn't explode in environments
    where the SDK isn't installed (e.g. CI schema checks).
    """
    _check_env()
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "openai>=1.50 is required. Install with: "
            "pip install -r pipeline/requirements.txt"
        ) from exc
    return OpenAI(
        base_url=os.environ["AZURE_KIMI_ENDPOINT"],
        api_key=os.environ["AZURE_KIMI_API_KEY"],
    )


def _model_name() -> str:
    return os.environ.get("AZURE_KIMI_MODEL", DEFAULT_MODEL)


# ---------------------------------------------------------------------------
# Prompt composition
# ---------------------------------------------------------------------------


def _candidate_user_prompt(kind: str, row: dict) -> str:
    """Render a candidate row as user-content for the LLM.

    Field names follow the Postgres schema (see pipeline/schema.sql). Missing
    fields are simply omitted. ``raw_readmes.content`` may be huge; the
    caller is expected to truncate to a reasonable prefix before calling.
    """
    if kind == "tools":
        parts = [
            f"Candidate kind: tool",
            f"Source URL: {row.get('source_url') or '(none)'}",
            f"Proposed id (pre-seed): {row.get('proposed_id') or '(none)'}",
            f"Name (pre-seed): {row.get('name') or '(none)'}",
            f"Summary: {row.get('summary') or '(none)'}",
        ]
        nlp = row.get("nlp_tags") or {}
        if nlp:
            parts.append(f"NLP pre-pass tags: {json.dumps(nlp)[:1000]}")
        readme = row.get("readme") or row.get("readme_text")
        if readme:
            parts.append("README (truncated):\n" + str(readme)[:8000])
        return "\n".join(parts)
    elif kind == "papers":
        parts = [
            f"Candidate kind: paper",
            f"Source URL: {row.get('source_url') or '(none)'}",
            f"Title (pre-seed): {row.get('title') or '(none)'}",
            f"Authors (pre-seed): {row.get('authors') or '(none)'}",
            f"Year (pre-seed): {row.get('year') or '(none)'}",
            f"Venue (pre-seed): {row.get('venue') or '(none)'}",
            f"DOI: {row.get('doi') or '(none)'}",
            f"arXiv id: {row.get('arxiv_id') or '(none)'}",
        ]
        abstract = row.get("abstract") or row.get("snippet")
        if abstract:
            parts.append("Abstract / snippet:\n" + str(abstract)[:6000])
        return "\n".join(parts)
    else:
        raise ValueError(f"Unknown candidate kind {kind!r}")


# ---------------------------------------------------------------------------
# Core call with retry + concurrency
# ---------------------------------------------------------------------------


def _http_status_from_exc(exc: BaseException) -> Optional[int]:
    """Best-effort extraction of an HTTP status code from an OpenAI SDK exc.

    Checks ``exc.status_code`` (set on ``openai.APIStatusError`` + subclasses)
    then ``exc.response.status_code``. Returns None when the exception is not
    HTTP-shaped — callers treat that as "transient" and use exp-backoff.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    if response is not None:
        rc = getattr(response, "status_code", None)
        if isinstance(rc, int):
            return rc
    return None


def _retry_after_seconds(exc: BaseException) -> Optional[float]:
    """Parse ``Retry-After`` from an OpenAI SDK exception's response headers.

    Returns the number of seconds to sleep, clamped to
    :data:`MAX_RETRY_AFTER_SECONDS`, or ``None`` when no header is present
    (or it's unparseable).
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("Retry-After") or headers.get("retry-after")
    except Exception:  # noqa: BLE001 - defensive against weird header mappings
        return None
    if not raw:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def _call_kimi_function(
    *,
    client,
    tool_name: str,
    tool_parameters: dict,
    system: str,
    user: str,
    max_tokens: int = MAX_TOKENS_DEFAULT,
    budget: Optional[CallBudget] = None,
) -> dict:
    """Invoke Kimi with function-calling structured output.

    Returns the JSON dict that the model passed as the function arguments.
    Raises on repeated failure or malformed output.

    When ``budget`` is non-None, one :meth:`CallBudget.consume` is recorded
    per HTTP call actually made (including failed attempts — they still cost
    the vendor). Passing the cap raises ``CostCapExceeded``.
    """
    if max_tokens < 2048:
        raise ValueError("max_tokens must be >= 2048 for Kimi-K2.5 (reasoning model).")

    tools = [
        {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": f"Record the structured extraction as {tool_name}.",
                "parameters": tool_parameters,
            },
        }
    ]
    tool_choice = {"type": "function", "function": {"name": tool_name}}

    last_exc: Optional[BaseException] = None
    for attempt in range(1, MAX_RETRIES + 1):
        resp = None
        try:
            with _concurrency_sem:
                resp = client.chat.completions.create(
                    model=_model_name(),
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    tools=tools,
                    tool_choice=tool_choice,
                    max_tokens=max_tokens,
                )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            # Use the real HTTP status (from openai.APIStatusError /
            # RateLimitError) rather than string-matching "429". Treat
            # 429 + 5xx as retryable; everything else propagates.
            status = _http_status_from_exc(exc)
            is_rate_limit = status == 429
            is_server_err = status is not None and 500 <= status < 600
            retryable = is_rate_limit or is_server_err or status is None

            # The request hit the wire even if we got an error back, so the
            # call still counts against the budget. This is a no-op when
            # budget is None.
            if budget is not None:
                budget.consume(call=True, tokens=0)

            if not retryable or attempt >= MAX_RETRIES:
                raise

            retry_after = _retry_after_seconds(exc) if is_rate_limit or is_server_err else None
            if retry_after is not None:
                backoff = retry_after
                backoff_source = f"Retry-After={retry_after:.1f}s"
            else:
                backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                backoff += random.uniform(0, 0.5)
                backoff_source = "exp-backoff"
            log.warning(
                "kimi call failed (attempt %d/%d, status=%s, %s): %s — backing off %.1fs",
                attempt, MAX_RETRIES, status, backoff_source, exc, backoff,
            )
            time.sleep(backoff)
            continue

        # Successful HTTP; record the call + usage tokens before parsing.
        if budget is not None:
            usage = getattr(resp, "usage", None)
            tokens = int(getattr(usage, "total_tokens", 0) or 0)
            budget.consume(call=True, tokens=tokens)

        choice = resp.choices[0]
        tool_calls = getattr(choice.message, "tool_calls", None) or []
        if not tool_calls:
            # Kimi-K2.5 sometimes emits tool calls as text inside `content` using
            # its own markup rather than the OpenAI `tool_calls` array. Parse that
            # fallback format before giving up.
            content = getattr(choice.message, "content", None) or ""
            parsed = _parse_kimi_inline_tool_call(content, tool_name)
            if parsed is not None:
                return parsed
            raise RuntimeError(
                f"Kimi returned no tool_calls (content={content[:200]!r}...). "
                f"Neither standard tool_calls nor inline Kimi markup found. "
                f"Likely max_tokens too low or model refused."
            )
        call = tool_calls[0]
        name = getattr(call.function, "name", None) or call.function.get("name")
        if name != tool_name:
            raise RuntimeError(
                f"Kimi returned wrong function name: {name!r} (expected {tool_name!r})"
            )
        args_json = getattr(call.function, "arguments", None) or call.function.get(
            "arguments"
        )
        try:
            return json.loads(args_json) if isinstance(args_json, str) else dict(args_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Kimi returned malformed JSON args: {exc}") from exc


def _parse_kimi_inline_tool_call(content: str, tool_name: str) -> dict | None:
    """Parse Kimi's `<|tool_calls_section_begin|>` text markup.

    Example payload (truncated):
        <|tool_calls_section_begin|><|tool_call_begin|>functions.record_tool:0
        <|tool_call_argument_begin|>{"name": {...}, ...}<|tool_call_end|>
        <|tool_calls_section_end|>

    Returns the parsed argument dict, or None if the markup is absent or
    malformed. Tolerant of truncation at max_tokens: if JSON is incomplete
    but at least the outer brace is present, attempt a best-effort close.
    """
    if "tool_calls_section_begin" not in content:
        return None
    # Pull text between the argument-begin marker and the next tool_call_end
    # (or end of string if truncated).
    start_marker = "<|tool_call_argument_begin|>"
    start = content.find(start_marker)
    if start < 0:
        return None
    start += len(start_marker)
    end_marker = "<|tool_call_end|>"
    end = content.find(end_marker, start)
    payload = content[start:end] if end >= 0 else content[start:]
    payload = payload.strip()
    if not payload.startswith("{"):
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        # Best-effort: balance braces for a truncated response.
        opens = payload.count("{")
        closes = payload.count("}")
        if opens > closes:
            try:
                return json.loads(payload + "}" * (opens - closes))
            except json.JSONDecodeError:
                pass
    return None

    # Should be unreachable due to the raise inside the loop.
    raise RuntimeError("Kimi call exhausted retries") from last_exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _github_license_spdx_from_row(candidate_row: dict) -> Optional[str]:
    """Pull ``raw_json.license.spdx_id`` from a candidate row if present.

    The caller may pass ``raw_json`` inline on the candidate dict (tests,
    bulk ingest), OR we fall back to looking up the most recent
    ``raw_search_results`` row with a matching ``source_url`` in Postgres.

    Returns a non-empty SPDX id string, or ``None`` when no authoritative
    license is available. ``NOASSERTION`` and ``other`` are treated as
    no-signal (GitHub uses them when it can't classify) and return ``None``.
    """
    # Inline raw_json path (used by tests + any caller that denormalised
    # the GitHub response onto the candidate dict).
    raw = candidate_row.get("raw_json")
    spdx = _spdx_from_raw_json(raw)
    if spdx:
        return spdx

    # DB fallback: only attempt if we have a source_url to match on and
    # pipeline.db is importable in this environment.
    source_url = candidate_row.get("source_url")
    if not source_url:
        return None
    try:
        from pipeline import db as _db  # local import; keeps module load cheap
    except Exception:  # noqa: BLE001
        return None
    sql = """
        SELECT raw_json
        FROM raw_search_results
        WHERE url = %s
        ORDER BY fetched_at DESC
        LIMIT 1
    """
    try:
        with _db.get_conn() as conn, conn.cursor() as cur:
            cur.execute(sql, (source_url,))
            row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        log.debug("license pre-seed db lookup failed: %s", exc)
        return None
    if not row:
        return None
    return _spdx_from_raw_json(row[0])


def _spdx_from_raw_json(raw: Any) -> Optional[str]:
    """Navigate a GitHub-API-shaped blob and return a clean SPDX id or None."""
    if not isinstance(raw, dict):
        return None
    lic = raw.get("license")
    if not isinstance(lic, dict):
        return None
    spdx = lic.get("spdx_id")
    if not isinstance(spdx, str):
        return None
    spdx = spdx.strip()
    if not spdx:
        return None
    # GitHub returns these sentinels when it can't classify — treat as absent.
    if spdx.upper() in {"NOASSERTION", "OTHER"}:
        return None
    return spdx


def _build_system_prompt(candidate_row: Optional[dict] = None) -> str:
    """Return the system prompt, optionally augmented with a license pre-seed.

    When ``candidate_row`` carries (or its ``source_url`` resolves to) a
    GitHub API response with a real SPDX id, append an authoritative block
    that tells the model to use it verbatim with confidence ~0.95.
    """
    prompt = SYSTEM_PROMPT
    if candidate_row is None:
        return prompt
    spdx = _github_license_spdx_from_row(candidate_row)
    if not spdx:
        return prompt
    preseed = (
        "\n## License pre-seed (authoritative)\n\n"
        f"The repo's GitHub API license field is `{spdx}`. Use this "
        "verbatim in the `license_spdx` output with confidence 0.95 unless "
        "the README explicitly contradicts it (e.g. a LICENSE file names a "
        "different SPDX id, or a sub-component carries a distinct license).\n"
    )
    return prompt + preseed


def extract_tool(
    candidate_row: dict,
    *,
    client=None,
    budget: Optional[CallBudget] = None,
) -> ToolExtraction:
    """Extract a ToolExtraction from a candidate_tools row.

    The client is instantiated on demand if not provided. Caller handles
    caching (see ``pipeline/extract/cache.py``). Pass a :class:`CallBudget`
    to cap calls/tokens across a batch; default ``None`` means no cap.
    """
    client = client or get_client()
    schema = _json_schema_for(ToolExtraction)
    system_prompt = _build_system_prompt(candidate_row)
    preseed_spdx = _github_license_spdx_from_row(candidate_row)
    args = _call_kimi_function(
        client=client,
        tool_name="record_tool",
        tool_parameters=schema,
        system=system_prompt,
        user=_candidate_user_prompt("tools", candidate_row),
        budget=budget,
    )
    extraction = ToolExtraction.model_validate(args)

    # If Kimi returned a different license_spdx than the pre-seed, keep
    # Kimi's value (it may have found a sub-license or fork) but log the
    # discrepancy so a reviewer can look.
    if preseed_spdx:
        returned = (
            extraction.license_spdx.value
            if extraction.license_spdx and isinstance(extraction.license_spdx.value, str)
            else None
        )
        if returned and returned.strip() and returned.strip() != preseed_spdx:
            log.warning(
                "license discrepancy for %s: github=%s kimi=%s — keeping kimi value",
                candidate_row.get("source_url") or "<unknown>",
                preseed_spdx,
                returned,
            )
    return extraction


def extract_paper(
    candidate_row: dict,
    *,
    client=None,
    budget: Optional[CallBudget] = None,
) -> PaperExtraction:
    """Extract a PaperExtraction from a candidate_papers row."""
    client = client or get_client()
    schema = _json_schema_for(PaperExtraction)
    args = _call_kimi_function(
        client=client,
        tool_name="record_paper",
        tool_parameters=schema,
        system=SYSTEM_PROMPT,
        user=_candidate_user_prompt("papers", candidate_row),
        budget=budget,
    )
    return PaperExtraction.model_validate(args)


def extract_batch(
    candidates: list[dict],
    kind: str,
    *,
    client=None,
    budget: Optional[CallBudget] = None,
) -> list[ToolExtraction | PaperExtraction]:
    """Parallelised batch extraction. Honours the global concurrency cap.

    Exceptions per-candidate are swallowed into a placeholder ``None`` entry
    in the result list; the caller decides how to log / retry. Index order
    matches ``candidates``. If a shared ``budget`` trips mid-batch the
    underlying :class:`CostCapExceeded` is stored as the row's result.
    """
    if kind not in ("tools", "papers"):
        raise ValueError(f"Unknown kind {kind!r}")
    client = client or get_client()
    fn = extract_tool if kind == "tools" else extract_paper
    results: list[Any] = [None] * len(candidates)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        fut_to_idx = {
            pool.submit(fn, row, client=client, budget=budget): idx
            for idx, row in enumerate(candidates)
        }
        for fut in as_completed(fut_to_idx):
            idx = fut_to_idx[fut]
            try:
                results[idx] = fut.result()
            except Exception as exc:  # noqa: BLE001
                log.error("extraction failed for candidate idx=%d: %s", idx, exc)
                results[idx] = None
    return results


# ---------------------------------------------------------------------------
# JSON-schema helpers
# ---------------------------------------------------------------------------


def _json_schema_for(model_cls) -> dict:
    """Return a JSON schema suitable for OpenAI function parameters.

    Pydantic v2's ``model_json_schema()`` produces a schema with
    ``$defs``; OpenAI tolerates that, but we strip fields the API rejects.
    """
    schema = model_cls.model_json_schema()
    # OpenAI rejects unknown top-level keys like ``title``; leaving it in
    # works today but is noisy — drop it.
    schema.pop("title", None)
    return schema


__all__ = [
    "FAILURE_MODE_DEFINITIONS",
    "SYSTEM_PROMPT",
    "_build_system_prompt",
    "_github_license_spdx_from_row",
    "extract_batch",
    "extract_paper",
    "extract_tool",
    "get_client",
]

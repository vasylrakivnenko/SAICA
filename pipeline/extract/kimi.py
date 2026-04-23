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

_concurrency_sem = threading.BoundedSemaphore(MAX_CONCURRENCY)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

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
  context_pollution, supply_chain_attack.
- LocusOfControl (multi-valued, subset): model, prompt, context,
  environment, human.

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
"""


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


def _call_kimi_function(
    *,
    client,
    tool_name: str,
    tool_parameters: dict,
    system: str,
    user: str,
    max_tokens: int = MAX_TOKENS_DEFAULT,
) -> dict:
    """Invoke Kimi with function-calling structured output.

    Returns the JSON dict that the model passed as the function arguments.
    Raises on repeated failure or malformed output.
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
            # Heuristically classify: anything with 429 in the message is a
            # rate-limit; otherwise treat as transient and retry-with-backoff
            # up to MAX_RETRIES.
            is_429 = "429" in str(exc) or "rate" in str(exc).lower()
            if attempt >= MAX_RETRIES:
                raise
            backoff = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            backoff += random.uniform(0, 0.5)
            log.warning(
                "kimi call failed (attempt %d/%d, 429=%s): %s — backing off %.1fs",
                attempt, MAX_RETRIES, is_429, exc, backoff,
            )
            time.sleep(backoff)
            continue

        choice = resp.choices[0]
        tool_calls = getattr(choice.message, "tool_calls", None) or []
        if not tool_calls:
            content = getattr(choice.message, "content", None)
            # This is the classic "max_tokens too low" symptom — raise loud.
            raise RuntimeError(
                f"Kimi returned no tool_calls (content={content!r}). "
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

    # Should be unreachable due to the raise inside the loop.
    raise RuntimeError("Kimi call exhausted retries") from last_exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_tool(candidate_row: dict, *, client=None) -> ToolExtraction:
    """Extract a ToolExtraction from a candidate_tools row.

    The client is instantiated on demand if not provided. Caller handles
    caching (see ``pipeline/extract/cache.py``).
    """
    client = client or get_client()
    schema = _json_schema_for(ToolExtraction)
    args = _call_kimi_function(
        client=client,
        tool_name="record_tool",
        tool_parameters=schema,
        system=SYSTEM_PROMPT,
        user=_candidate_user_prompt("tools", candidate_row),
    )
    return ToolExtraction.model_validate(args)


def extract_paper(candidate_row: dict, *, client=None) -> PaperExtraction:
    """Extract a PaperExtraction from a candidate_papers row."""
    client = client or get_client()
    schema = _json_schema_for(PaperExtraction)
    args = _call_kimi_function(
        client=client,
        tool_name="record_paper",
        tool_parameters=schema,
        system=SYSTEM_PROMPT,
        user=_candidate_user_prompt("papers", candidate_row),
    )
    return PaperExtraction.model_validate(args)


def extract_batch(
    candidates: list[dict],
    kind: str,
    *,
    client=None,
) -> list[ToolExtraction | PaperExtraction]:
    """Parallelised batch extraction. Honours the global concurrency cap.

    Exceptions per-candidate are swallowed into a placeholder ``None`` entry
    in the result list; the caller decides how to log / retry. Index order
    matches ``candidates``.
    """
    if kind not in ("tools", "papers"):
        raise ValueError(f"Unknown kind {kind!r}")
    client = client or get_client()
    fn = extract_tool if kind == "tools" else extract_paper
    results: list[Any] = [None] * len(candidates)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        fut_to_idx = {
            pool.submit(fn, row, client=client): idx
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
    "SYSTEM_PROMPT",
    "extract_batch",
    "extract_paper",
    "extract_tool",
    "get_client",
]

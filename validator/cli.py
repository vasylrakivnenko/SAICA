#!/usr/bin/env python3
"""SAICA-KG validator: the gate every change to ``data/`` must pass.

What it checks, all offline and from the files alone:

* every YAML file loads (no syntax error, no key written twice, ``.yml``
  extension) and parses into its Pydantic model in :mod:`pipeline.models`
  with strict JSON typing, so the gate accepts what the published
  ``schema/*.json`` accepts and nothing more;
* per file: ``id`` equals the file name, no empty (null) values, no
  placeholder text, no list entry written twice, URLs are ``http(s)``, no
  date in the future, dates in order;
* across files: ids are unique, no paper or tool is entered twice (same
  arXiv id, DOI, URL, title or repository), every reference points at a
  node that exists, every failure mode in the enum has a file, recipes
  target modes their stack addresses, a taxonomy that still says its
  labels are unverified is not mapped, removed nodes have a tombstone.

Network checks (dead links, arXiv titles) are opt-in flags and live in
:mod:`validator.netchecks`; they never run by default.

Usage:
    python validator/cli.py                 # validate data/
    python validator/cli.py --strict        # warnings fail too
    python validator/cli.py --only tools    # schema pass for some kinds only;
                                            # cross-file checks always run
    python validator/cli.py --data-dir /tmp/copy/data   # another tree
    python validator/cli.py --arxiv --offline   # titles vs the tracked cache
    python validator/cli.py --arxiv --links     # network, cached
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    import yaml
except ImportError:
    print(
        "Missing dependency: pyyaml. Install with: pip install pyyaml pydantic",
        file=sys.stderr,
    )
    sys.exit(2)

try:
    from pydantic import ValidationError
except ImportError:
    print(
        "Missing dependency: pydantic. Install with: pip install pyyaml pydantic",
        file=sys.stderr,
    )
    sys.exit(2)


REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
MANIFEST_PATH = DATA_DIR / "MANIFEST.json"

# Ensure the repo root is importable whether this script is invoked directly
# (``python validator/cli.py``) or as a module (``python -m validator.cli``).
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline.models import (  # noqa: E402
    FAILURE_MODE_IDS,
    NODE_MODELS,
    AutonomyLevel,
    ControlParadigm,
    LocusOfControl,
    TemporalPhase,
)

STALE_AT_RISK_DAYS = 365  # upstream silent for longer than this => at_risk

# The failure-mode ids come from one place: pipeline.models.FailureModeId.
KNOWN_FAILURE_MODE_IDS = frozenset(FAILURE_MODE_IDS)

# Values a crosswalk may map to, per SAICA axis.
AXIS_VALUES: dict[str, frozenset[str]] = {
    "failure_mode": KNOWN_FAILURE_MODE_IDS,
    "control_paradigm": frozenset(m.value for m in ControlParadigm),
    "temporal_phase": frozenset(m.value for m in TemporalPhase),
    "autonomy_level": frozenset(m.value for m in AutonomyLevel),
    "locus_of_control": frozenset(m.value for m in LocusOfControl),
}

# Fields whose published JSON Schema allows an explicit null.
NULLABLE_FIELDS = frozenset(
    name
    for model in NODE_MODELS.values()
    for name, info in model.model_fields.items()
    if isinstance(info.json_schema_extra, dict)
    and info.json_schema_extra.get("_keep_null")
)

URL_FIELDS = frozenset({"repository_url", "documentation_url", "url"})
URL_LIST_FIELDS = frozenset({"source_urls"})

# List fields where the same value twice is legitimate (two authors can
# share a name).
DUPLICATES_ALLOWED = frozenset({"authors"})

# Sentinels the April ingestion pipeline wrote for "a person must fill this".
_SENTINEL_RE = re.compile(r"REVIEW[_ ]REQUIRED")
# A value that is only a placeholder, or starts with one.
_PLACEHOLDER_START_RE = re.compile(r"^(TODO|TBD|FIXME|XXX|PLACEHOLDER|CHANGEME)\b")
_PLACEHOLDER_WHOLE = frozenset(
    {
        "todo",
        "tbd",
        "fixme",
        "xxx",
        "placeholder",
        "changeme",
        "fill me in",
        "to be done",
        "to be determined",
        "???",
    }
)

_ET_AL_RE = re.compile(r"\bet\.?\s+al\b\.?|^(and\s+)?others$", re.IGNORECASE)

# Notes that say the labels of a taxonomy were never checked against the
# source. The first group blocks crosswalks (error); the second is a warning.
_SEED_NOTE_RES = (
    re.compile(r"paraphrased\s+for\s+seed", re.IGNORECASE),
    re.compile(r"verify\b[^.]{0,80}\bbefore\b[^.]{0,40}\brelease", re.IGNORECASE),
)
_UNVERIFIED_NOTE_RES = (
    re.compile(r"\bparaphrased\s+from\b", re.IGNORECASE),
    re.compile(r"pending\b[^.]{0,40}\bverification", re.IGNORECASE),
)

# ``evaluated_on`` may name a paper node or a release of the project's own
# benchmark (``saica-bench``, ``saica-bench-2026``, ``saica-bench-2026-11``).
_BENCH_ID_RE = re.compile(r"^saica-bench(-[0-9]{4}(-[0-9]{2})?)?$")

TOMBSTONE_KINDS = {
    "tool": "tools",
    "failure_mode": "failure_modes",
    "paper": "papers",
    "taxonomy": "taxonomies",
    "crosswalk": "crosswalks",
    "incident": "incidents",
    "recipe": "recipes",
}

Nodes = dict[str, list[tuple[Path, dict[str, Any]]]]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


class _UniqueKeyLoader(yaml.SafeLoader):
    """``yaml.SafeLoader`` that refuses a mapping with the same key twice.

    Plain PyYAML keeps the last value and says nothing, so a second
    ``addresses_failure_modes:`` block silently replaces the first.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            try:
                key = self.construct_object(key_node, deep=True)
                hash(key)
            except TypeError:
                continue
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None,
                    None,
                    f"key '{key}' is written twice (line {key_node.start_mark.line + 1})",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _coerce(value: Any) -> Any:
    """Coerce ``datetime.date`` values back to ISO strings so Pydantic's
    YAML output matches its JSON-input expectations. Also recurses into
    dicts/lists.
    """
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _coerce(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce(v) for v in value]
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML mapping. Raises ``ValueError`` with a one-line reason
    (syntax error, repeated key, top level not a mapping)."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.load(
                fh, Loader=_UniqueKeyLoader
            )  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        reason = " ".join(str(exc).split())
        raise ValueError(f"cannot be read as YAML: {reason}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot be read: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("top level must be a mapping")
    return _coerce(data)


def read_kind(
    kind: str, data_dir: Path | None = None
) -> tuple[list[tuple[Path, dict[str, Any]]], list[str]]:
    """Return ``(nodes, load_errors)`` for one node kind.

    A file that cannot be loaded becomes an error line that names it; it is
    left out of ``nodes`` so one bad file does not hide the rest.
    """
    subdir = (data_dir or DATA_DIR) / kind
    nodes: list[tuple[Path, dict[str, Any]]] = []
    errors: list[str] = []
    if not subdir.exists():
        return nodes, errors
    for path in sorted(subdir.glob("*.yaml")):
        errors.append(
            f"[{kind}] {path.name} :: <file> — use the .yml extension; the site and"
            " the served loaders read only *.yml and would drop this node"
        )
    for path in sorted(subdir.glob("*.yml")) + sorted(subdir.glob("*.yaml")):
        try:
            nodes.append((path, load_yaml(path)))
        except ValueError as exc:
            errors.append(f"[{kind}] {path.name} :: <file> — {exc}")
    return nodes, errors


def iter_nodes(kind: str) -> list[tuple[Path, dict[str, Any]]]:
    """Loadable nodes of one kind under ``DATA_DIR`` (load errors dropped;
    :func:`read_kind` reports them)."""
    return read_kind(kind)[0]


def load_corpus(data_dir: Path | None = None) -> tuple[Nodes, list[str]]:
    """Parse every node file once. Returns ``(nodes by kind, load errors)``."""
    nodes: Nodes = {}
    errors: list[str] = []
    for kind in NODE_MODELS:
        nodes[kind], kind_errors = read_kind(kind, data_dir)
        errors.extend(kind_errors)
    return nodes, errors


# ---------------------------------------------------------------------------
# Per-file checks
# ---------------------------------------------------------------------------


def _fmt_loc(loc: tuple[Any, ...]) -> str:
    return "/".join(str(x) for x in loc) or "<root>"


def _format_pydantic_error(err: dict[str, Any]) -> str:
    """Format one entry from :meth:`ValidationError.errors()`.

    Pydantic produces richer error types than jsonschema (``extra_forbidden``,
    ``missing``, ``string_pattern_mismatch``, ``enum``, etc.). We reshape
    these to be at least as clear as the jsonschema text that used to be
    emitted here.
    """
    etype = err.get("type", "")
    msg = err.get("msg", "")
    ctx = err.get("ctx") or {}
    inp = err.get("input")

    if etype == "extra_forbidden":
        return (
            f"Additional properties are not allowed ('{err['loc'][-1]}' was unexpected)"
        )
    if etype == "missing":
        return f"'{err['loc'][-1]}' is a required property"
    if etype == "enum":
        expected = ctx.get("expected", "")
        return f"{inp!r} is not one of {expected}"
    if etype == "string_pattern_mismatch":
        pat = ctx.get("pattern", "")
        return f"{inp!r} does not match pattern {pat!r}"
    return msg


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str) or value != value.strip() or " " in value:
        return False
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and "." in parts.netloc


def _walk(value: Any, path: tuple[Any, ...] = ()):
    """Yield ``(path, value)`` for every value in a nested dict / list."""
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, path + (index,))


def _is_placeholder(text: str) -> bool:
    stripped = text.strip()
    return (
        bool(_SENTINEL_RE.search(stripped))
        or bool(_PLACEHOLDER_START_RE.match(stripped))
        or stripped.strip("<>[](){}.!").strip().lower() in _PLACEHOLDER_WHOLE
    )


def _parse_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _date_fields(model: type) -> set[str]:
    """Names of the date-typed fields of a model and its nested models."""
    names: set[str] = set()
    for name, info in model.model_fields.items():
        annotation = str(info.annotation)
        if "datetime.date" in annotation:
            names.add(name)
    return names


_DATE_FIELDS: dict[str, set[str]] = {
    kind: _date_fields(model) for kind, model in NODE_MODELS.items()
}
# Nested blocks that carry dates.
_NESTED_DATE_FIELDS = {"ingested_at", "review_date", "at"}

# (earlier field, later field, days of slack) — the later one must not be
# before the earlier one. One day of slack covers time-zone differences
# between a UTC push time and a local review date.
_DATE_ORDER: dict[str, tuple[tuple[str, str, int], ...]] = {
    "tools": (
        ("first_released", "last_updated", 0),
        ("first_released", "upstream_pushed_at", 0),
        ("upstream_pushed_at", "last_reviewed", 1),
    ),
    "taxonomies": (("first_published", "last_updated", 0),),
}


def file_errors(
    kind: str, path: Path, node: dict[str, Any], *, as_of: dt.date
) -> list[str]:
    """Checks on one file that the schema cannot express."""
    errors: list[str] = []
    name = path.name

    def add(loc: str, message: str) -> None:
        errors.append(f"[{kind}] {name} :: {loc} — {message}")

    node_id = node.get("id")
    if isinstance(node_id, str) and node_id != path.stem:
        add(
            "id",
            f"id '{node_id}' does not equal the file name '{path.stem}';"
            " loaders that key by file name and by id would disagree",
        )

    # The sentinel also counts when it sits in a YAML comment.
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        raw_lines = []
    for lineno, line in enumerate(raw_lines, start=1):
        if _SENTINEL_RE.search(line):
            add(
                f"line {lineno}",
                "REVIEW_REQUIRED marker left in the file; a person must fill"
                " the field and remove the marker",
            )

    future_limit = as_of + dt.timedelta(days=1)
    for loc, value in _walk(node):
        if not loc:
            continue
        key = loc[-1]
        where = _fmt_loc(loc)
        if value is None:
            if key not in NULLABLE_FIELDS:
                add(where, "is empty (null); delete the key or give it a value")
            continue
        if isinstance(value, str):
            if _is_placeholder(value) and not _SENTINEL_RE.search(value):
                add(where, f"placeholder text {value.strip()[:40]!r} is not a value")
            if key in URL_FIELDS and not _is_http_url(value):
                add(where, f"{value!r} is not an http(s) URL")
            if (
                len(loc) >= 2
                and loc[-2] in URL_LIST_FIELDS
                and isinstance(key, int)
                and not _is_http_url(value)
            ):
                add(where, f"{value!r} is not an http(s) URL")
            is_date_field = (len(loc) == 1 and key in _DATE_FIELDS.get(kind, ())) or (
                len(loc) == 2 and key in _NESTED_DATE_FIELDS
            )
            if is_date_field:
                parsed = _parse_date(value)
                if parsed is not None and parsed > future_limit:
                    add(where, f"{value} is in the future")
        if isinstance(value, list) and key not in DUPLICATES_ALLOWED:
            seen: set[Any] = set()
            for item in value:
                if not isinstance(item, (str, int, float)):
                    continue
                if item in seen:
                    add(where, f"'{item}' is listed twice")
                seen.add(item)

    for earlier, later, slack in _DATE_ORDER.get(kind, ()):
        first, second = _parse_date(node.get(earlier)), _parse_date(node.get(later))
        if first and second and second + dt.timedelta(days=slack) < first:
            add(later, f"{second} is before {earlier} {first}")

    if kind == "papers":
        for index, author in enumerate(node.get("authors") or []):
            if isinstance(author, str) and _ET_AL_RE.search(author.strip()):
                add(
                    f"authors/{index}",
                    f"{author!r} is not an author; list every name on the byline",
                )
        year = node.get("year")
        if isinstance(year, int) and year > as_of.year + 1:
            add("year", f"{year} is in the future")
        if node.get("arxiv_version") and not node.get("arxiv_id"):
            add("arxiv_version", "is set but the record has no arxiv_id")
        if node.get("provenance") == "arxiv-api" and not node.get("arxiv_id"):
            add("provenance", "'arxiv-api' needs an arxiv_id")
        if node.get("provenance") == "crossref-api" and not node.get("doi"):
            add("provenance", "'crossref-api' needs a doi")

    if kind == "crosswalks":
        state = node.get("review_state")
        reviewers = node.get("reviewed_by") or []
        if state == "human_reviewed" and not reviewers:
            add("review_state", "'human_reviewed' needs the reviewers in reviewed_by")
        if state == "llm_drafted_unreviewed" and reviewers:
            add(
                "review_state",
                "'llm_drafted_unreviewed' contradicts a non-empty reviewed_by",
            )
        if node.get("last_reviewed") and not reviewers:
            add(
                "last_reviewed",
                "a review date needs the reviewers in reviewed_by; for a check"
                " of ids and labels against the source use source_checked_on",
            )

    return errors


def schema_errors(
    kind: str,
    nodes: list[tuple[Path, dict[str, Any]]] | None = None,
    *,
    as_of: dt.date | None = None,
) -> list[str]:
    """Schema errors plus the per-file checks for every node of one kind."""
    model = NODE_MODELS[kind]
    as_of = as_of or dt.date.today()
    errors: list[str] = []
    for path, node in nodes if nodes is not None else iter_nodes(kind):
        try:
            # Strict JSON typing: '12' is not an integer and 'yes' is not a
            # boolean, exactly as in the published schema/*.json.
            model.model_validate_json(json.dumps(node), strict=True)
        except ValidationError as exc:
            for e in exc.errors():
                loc = _fmt_loc(e.get("loc", ()))
                msg = _format_pydantic_error(e)
                errors.append(f"[{kind}] {path.name} :: {loc} — {msg}")
        except (TypeError, ValueError) as exc:
            errors.append(f"[{kind}] {path.name} :: <root> — {exc}")
        errors.extend(file_errors(kind, path, node, as_of=as_of))
    return errors


# ---------------------------------------------------------------------------
# Cross-file checks
# ---------------------------------------------------------------------------


def _index(
    kind: str, entries: list[tuple[Path, dict[str, Any]]], err: list[str]
) -> dict[str, dict[str, Any]]:
    """Index nodes by id; report ids used by more than one file."""
    out: dict[str, dict[str, Any]] = {}
    first_file: dict[str, str] = {}
    for path, node in entries:
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            # The schema pass reports the missing id; skip it here.
            continue
        if node_id in out:
            err.append(
                f"[{kind}] id '{node_id}' is used by two files:"
                f" {first_file[node_id]} and {path.name}"
            )
            continue
        out[node_id] = node
        first_file[node_id] = path.name
    return out


def _strs(value: Any) -> list[str]:
    """A YAML list field as a list of strings; null, scalars and non-string
    items never crash a check (the schema pass reports them)."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


def _norm_arxiv(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower().removeprefix("arxiv:")
    return re.sub(r"v[0-9]+$", "", text) or None


def _norm_doi(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", value.strip().lower())
    return text.removeprefix("doi:") or None


def _norm_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().lower()
    text = re.sub(r"^http://", "https://", text)
    text = re.sub(r"^https://www\.", "https://", text)
    text = re.sub(r"(\.git)?/*$", "", text)
    text = re.sub(r"(arxiv\.org/(abs|pdf)/[0-9.]+)v[0-9]+$", r"\1", text)
    return text or None


def _norm_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return re.sub(r"[^a-z0-9]+", "", value.casefold()) or None


def _duplicates(
    kind: str,
    nodes: dict[str, dict[str, Any]],
    fields: tuple[tuple[str, Any], ...],
    err: list[str],
) -> None:
    """Error when two nodes of a kind share a normalised field value."""
    for field, normalise in fields:
        seen: dict[str, str] = {}
        for node_id in sorted(nodes):
            key = normalise(nodes[node_id].get(field))
            if key is None:
                continue
            if key in seen:
                err.append(
                    f"[{kind}] {node_id} has the same {field} as {seen[key]}:"
                    f" {nodes[node_id].get(field)!r} — one work, one node"
                )
            else:
                seen[key] = node_id


def _taxonomy_unverified(tax: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(blocking phrase, soft phrase)`` found in a taxonomy's notes.

    Both are ``None`` once ``verified_against_source`` carries a date: the
    notes may then quote the old wording as history.
    """
    if tax.get("verified_against_source"):
        return None, None
    notes = tax.get("notes")
    if not isinstance(notes, str):
        return None, None
    hard = next((m.group(0) for r in _SEED_NOTE_RES if (m := r.search(notes))), None)
    soft = next(
        (m.group(0) for r in _UNVERIFIED_NOTE_RES if (m := r.search(notes))), None
    )
    return hard, soft


def _bench_rows_for(tool_id: str, data_dir: Path) -> bool | None:
    """True/False when the benchmark results file next to ``data_dir`` can
    answer "does this tool have a measured row?"; None when it cannot."""
    results = data_dir.parent / "site" / "public" / "bench" / "results.json"
    try:
        doc = json.loads(results.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    modes = doc.get("modes") if isinstance(doc, dict) else None
    if not isinstance(modes, list):
        return None
    for mode in modes:
        for row in (mode.get("rows") if isinstance(mode, dict) else None) or []:
            if isinstance(row, dict) and row.get("kg_id") == tool_id:
                return True
    return False


def cross_invariants(
    warn: list[str],
    err: list[str],
    nodes: Nodes | None = None,
    *,
    data_dir: Path | None = None,
) -> None:
    """Checks that span several files and cannot live in a per-file schema.

    ``nodes`` defaults to what :func:`iter_nodes` returns, which is what
    the unit tests replace with small fixtures.
    """
    if nodes is None:
        nodes = {kind: iter_nodes(kind) for kind in NODE_MODELS}
    data_dir = data_dir or DATA_DIR

    tools = _index("tools", nodes.get("tools", []), err)
    modes = _index("failure_modes", nodes.get("failure_modes", []), err)
    papers = _index("papers", nodes.get("papers", []), err)
    taxonomies = _index("taxonomies", nodes.get("taxonomies", []), err)
    crosswalks = _index("crosswalks", nodes.get("crosswalks", []), err)
    incidents = _index("incidents", nodes.get("incidents", []), err)
    recipes = _index("recipes", nodes.get("recipes", []), err)

    # --- the same work or tool entered twice ---------------------------
    _duplicates(
        "papers",
        papers,
        (
            ("arxiv_id", _norm_arxiv),
            ("doi", _norm_doi),
            ("url", _norm_url),
            ("title", _norm_title),
        ),
        err,
    )
    _duplicates("tools", tools, (("repository_url", _norm_url),), err)

    # --- failure modes: the enum and the files must agree ----------------
    for mode_id in sorted(modes):
        if mode_id not in KNOWN_FAILURE_MODE_IDS:
            err.append(
                f"[failure_modes] {mode_id} is not a value of"
                " pipeline.models.FailureModeId; add it there first"
            )
    if modes:
        for mode_id in sorted(KNOWN_FAILURE_MODE_IDS - set(modes)):
            err.append(
                f"[failure_modes] {mode_id} has no file in data/failure_modes/"
                " but is a value of pipeline.models.FailureModeId"
            )
    known_modes = KNOWN_FAILURE_MODE_IDS

    def category_ids(tax_id: str) -> set[str]:
        return {
            c["external_id"]
            for c in taxonomies[tax_id].get("categories", []) or []
            if isinstance(c, dict) and "external_id" in c
        }

    unverified: dict[str, str] = {}
    for tax_id in sorted(taxonomies):
        hard, soft = _taxonomy_unverified(taxonomies[tax_id])
        if hard:
            unverified[tax_id] = hard
        elif soft:
            warn.append(
                f"[taxonomies] {tax_id}: notes say the labels are not verified"
                f" against the source ('{soft}'); check them and set"
                " verified_against_source"
            )

    def unverified_error(owner: str, tax_id: str) -> None:
        err.append(
            f"{owner} maps to taxonomy '{tax_id}', whose notes say its labels"
            f" were never checked against the source ('{unverified[tax_id]}')."
            " Check the labels and set verified_against_source on the taxonomy,"
            " or remove the mapping"
        )

    for mode_id, mode in modes.items():
        for pid in _strs(mode.get("prior_work")):
            if pid not in papers:
                err.append(f"[failure_modes] {mode_id} cites missing paper '{pid}'")
        for other in _strs(mode.get("related_modes")):
            if other == mode_id:
                err.append(f"[failure_modes] {mode_id} related_modes names itself")
            elif other not in known_modes:
                err.append(
                    f"[failure_modes] {mode_id} related_modes names unknown"
                    f" FailureMode '{other}'"
                )
            elif other in modes and mode_id not in _strs(
                modes[other].get("related_modes")
            ):
                err.append(
                    f"[failure_modes] {mode_id} lists '{other}' in related_modes"
                    f" but {other} does not list {mode_id}; the relation goes"
                    " both ways"
                )
        source = mode.get("canonical_definition_source")
        if isinstance(source, str) and source not in papers:
            err.append(
                f"[failure_modes] {mode_id} canonical_definition_source is"
                f" missing paper '{source}'"
            )
        for cw in mode.get("crosswalks", []) or []:
            if not isinstance(cw, dict):
                continue
            tax_id = cw.get("taxonomy")
            if tax_id not in taxonomies:
                err.append(
                    f"[failure_modes] {mode_id} crosswalk references missing taxonomy"
                    f" '{tax_id}'"
                )
                continue
            if tax_id in unverified:
                unverified_error(f"[failure_modes] {mode_id} crosswalk", tax_id)
            # Inline FailureMode crosswalks: external_id must be a category of
            # the referenced taxonomy.
            ext = cw.get("external_id")
            if ext is not None and ext not in category_ids(tax_id):
                err.append(
                    f"[failure_modes] {mode_id} crosswalk external_id '{ext}' "
                    f"is not a category of taxonomy '{tax_id}'"
                )

    # Standalone Crosswalk nodes: each mapping's external_id must exist in
    # the target taxonomy's categories, and saica_value on the SAICA axis.
    for cw_id, cw in crosswalks.items():
        tax_id = cw.get("taxonomy")
        if tax_id not in taxonomies:
            err.append(f"[crosswalks] {cw_id} references missing taxonomy '{tax_id}'")
            continue
        if tax_id in unverified:
            unverified_error(f"[crosswalks] {cw_id}", tax_id)
        known_ext_ids = category_ids(tax_id)
        axis_values = AXIS_VALUES.get(str(cw.get("saica_axis")))
        mapped: set[str] = set()
        for m in cw.get("mappings", []) or []:
            if not isinstance(m, dict):
                continue
            value = m.get("saica_value")
            if axis_values is not None and value not in axis_values:
                err.append(
                    f"[crosswalks] {cw_id} mapping saica_value '{value}' is not a"
                    f" value of the {cw.get('saica_axis')} axis"
                )
            ext = m.get("external_id")
            if ext is None:
                continue
            mapped.add(ext)
            if ext not in known_ext_ids:
                err.append(
                    f"[crosswalks] {cw_id} mapping saica={m.get('saica_value')} -> "
                    f"external={ext} not a category of taxonomy '{tax_id}'"
                )
        listed: set[str] = set()
        for u in cw.get("unmapped", []) or []:
            if not isinstance(u, dict):
                continue
            cat = u.get("category")
            if cat not in known_ext_ids:
                err.append(
                    f"[crosswalks] {cw_id} unmapped category '{cat}' is not a"
                    f" category of taxonomy '{tax_id}'"
                )
            elif cat in mapped:
                err.append(
                    f"[crosswalks] {cw_id} lists category '{cat}' as unmapped"
                    " and also maps it"
                )
            elif cat in listed:
                err.append(
                    f"[crosswalks] {cw_id} lists unmapped category '{cat}' twice"
                )
            listed.add(cat)
        if cw.get("unmapped") is not None:
            # A crosswalk that lists what it leaves out claims to be complete:
            # every category is mapped, listed as unmapped, or sits under a
            # parent that is. A parent is covered by its children.
            parent_of = {
                c.get("external_id"): c.get("parent_id")
                for c in taxonomies[tax_id].get("categories", []) or []
                if isinstance(c, dict)
            }
            has_children = {p for p in parent_of.values() if p is not None}
            decided = mapped | listed

            def accounted(cat: Any) -> bool:
                hops = 0
                while cat is not None and hops < 50:
                    if cat in decided:
                        return True
                    cat, hops = parent_of.get(cat), hops + 1
                return False

            for cat in sorted(known_ext_ids - has_children):
                if not accounted(cat):
                    err.append(
                        f"[crosswalks] {cw_id}: category '{cat}' of taxonomy"
                        f" '{tax_id}' is neither mapped nor listed under unmapped"
                    )

    # Taxonomy nodes: paper_id must be a known paper, and every category's
    # parent_id must be an external_id defined in the same taxonomy.
    for tax_id, tax in taxonomies.items():
        pid = tax.get("paper_id")
        if pid is not None and pid not in papers:
            err.append(
                f"[taxonomies] {tax_id} paper_id references missing paper '{pid}'"
            )
        cats = [c for c in tax.get("categories", []) or [] if isinstance(c, dict)]
        cat_ids = {c.get("external_id") for c in cats}
        seen_cats: set[Any] = set()
        for c in cats:
            ext = c.get("external_id")
            if ext in seen_cats:
                err.append(f"[taxonomies] {tax_id} category '{ext}' is defined twice")
            seen_cats.add(ext)
            parent = c.get("parent_id")
            if parent is not None and parent not in cat_ids:
                err.append(
                    f"[taxonomies] {tax_id} category {c.get('external_id')} has "
                    f"parent_id '{parent}' that is not a category of this taxonomy"
                )

    composes: dict[str, set[str]] = defaultdict(set)
    supersedes_edges: list[tuple[str, str]] = []

    for tid, tool in tools.items():
        for pid in _strs(tool.get("cited_in")) + _strs(tool.get("documented_in")):
            if pid not in papers:
                err.append(f"[tools] {tid} cites missing paper '{pid}'")
        for ref in _strs(tool.get("evaluated_on")):
            if ref in papers:
                continue
            if not _BENCH_ID_RE.match(ref):
                err.append(
                    f"[tools] {tid} evaluated_on '{ref}' is neither a paper id"
                    " nor a SAICA-Bench release (saica-bench[-YYYY[-MM]])"
                )
            elif _bench_rows_for(tid, data_dir) is False:
                err.append(
                    f"[tools] {tid} evaluated_on '{ref}' but the benchmark"
                    " results have no row for this tool"
                )
        addressed = _strs(tool.get("addresses_failure_modes"))
        for fm in addressed:
            if fm not in known_modes:
                err.append(f"[tools] {tid} addresses unknown FailureMode '{fm}'")
        for fm in _strs(tool.get("records_failure_modes")):
            if fm not in known_modes:
                err.append(f"[tools] {tid} records unknown FailureMode '{fm}'")
            if fm in addressed:
                err.append(
                    f"[tools] {tid} lists '{fm}' in both addresses_ and records_failure_modes"
                )
        for field in ("composes_with", "feeds_into", "supersedes"):
            for other in _strs(tool.get(field)):
                if other == tid:
                    err.append(f"[tools] {tid} {field} names itself")
                elif other not in tools:
                    err.append(f"[tools] {tid} {field} missing tool '{other}'")
                if field == "composes_with":
                    composes[tid].add(other)
                if field == "supersedes":
                    supersedes_edges.append((tid, other))

        # Staleness is judged at the date the entry was last checked, so the
        # warning depends on the data and not on the day the gate runs.
        pushed = _parse_date(tool.get("upstream_pushed_at") or tool.get("last_updated"))
        checked = _parse_date(tool.get("last_reviewed") or tool.get("stars_updated_at"))
        status = tool.get("maturity_status")
        if pushed and checked:
            age = (checked - pushed).days
            if age > STALE_AT_RISK_DAYS and status not in (
                "at_risk",
                "deprecated",
                "abandoned",
            ):
                warn.append(
                    f"[tools] {tid}: no upstream push for {age} days when last"
                    f" checked on {checked}; should be at_risk"
                )
        if tool.get("archived") is True and status in ("stable", "experimental"):
            warn.append(
                f"[tools] {tid}: upstream repository is archived but"
                f" maturity_status is '{status}'"
            )

    for a, bs in composes.items():
        for b in bs:
            if b in tools and a != b and a not in composes.get(b, set()):
                warn.append(
                    f"[tools] composes_with is not symmetric: {a} → {b} but not {b} → {a}"
                )

    if has_cycle(supersedes_edges):
        err.append("[tools] supersedes graph contains a cycle")

    for tid, tool in tools.items():
        if not tool.get("signed_manifest") and not tool.get("security_notes"):
            warn.append(
                f"[tools] {tid}: neither signed_manifest nor security_notes populated"
            )
        if not tool.get("cited_in"):
            warn.append(f"[tools] {tid}: no cited_in papers")

    mitigated: dict[str, set[str]] = defaultdict(set)
    for tid, tool in tools.items():
        for fm in _strs(tool.get("addresses_failure_modes")):
            mitigated[fm].add(tid)
    for mode_id in modes:
        if len(mitigated[mode_id]) < 3:
            warn.append(
                f"[failure_modes] {mode_id}: only {len(mitigated[mode_id])} mitigating tools"
                f" (under-covered)"
            )

    # Incident invariants: exhibited failure modes must be known; cited paper
    # and tool ids must exist. This keeps Incident nodes from drifting into
    # dangling references over time.
    unverified_urls = {
        _norm_url(taxonomies[t].get("url")): t
        for t in unverified
        if _norm_url(taxonomies[t].get("url"))
    }
    for inc_id, inc in incidents.items():
        for fm in _strs(inc.get("exhibited_failure_modes")):
            if fm not in known_modes:
                err.append(f"[incidents] {inc_id} exhibited unknown FailureMode '{fm}'")
        for pid in _strs(inc.get("documented_by")):
            if pid not in papers:
                err.append(f"[incidents] {inc_id} documented_by missing paper '{pid}'")
        for tid in _strs(inc.get("mitigated_by")):
            if tid not in tools:
                err.append(f"[incidents] {inc_id} mitigated_by missing tool '{tid}'")
        # An incident "references" a taxonomy when it cites the taxonomy's
        # own source or one of its category ids.
        text = " ".join(
            str(inc.get(k) or "") for k in ("title", "tagline", "description", "notes")
        )
        cited = {_norm_url(u) for u in _strs(inc.get("source_urls"))}
        for tax_id in sorted(unverified):
            by_url = any(u in cited for u, t in unverified_urls.items() if t == tax_id)
            by_id = any(
                re.search(rf"(?<![\w-]){re.escape(str(ext))}(?![\w-])", text)
                for ext in category_ids(tax_id)
            )
            if by_url or by_id:
                err.append(
                    f"[incidents] {inc_id} rests on taxonomy '{tax_id}', whose"
                    " notes say its labels were never checked against the source"
                    f" ('{unverified[tax_id]}')"
                )

    # Recipe invariants: every tool in `stack` must be a known Tool id;
    # targets_failure_modes must be known and addressed by the stack.
    for rec_id, rec in recipes.items():
        stack = _strs(rec.get("stack"))
        for tid in stack:
            if tid not in tools:
                err.append(f"[recipes] {rec_id} stack references missing tool '{tid}'")
        stack_addresses = {
            fm
            for tid in stack
            for fm in _strs(tools.get(tid, {}).get("addresses_failure_modes"))
        }
        for fm in _strs(rec.get("targets_failure_modes")):
            if fm not in known_modes:
                err.append(f"[recipes] {rec_id} targets unknown FailureMode '{fm}'")
            elif fm not in stack_addresses:
                err.append(
                    f"[recipes] {rec_id} targets '{fm}' but no tool in its stack"
                    " addresses that mode"
                )

    # ID-immutability lock: every id in the committed MANIFEST.json must
    # still exist in the YAML corpus or carry a tombstone. A missing id
    # means someone renamed or deleted a node, breaking external citations.
    live = {
        "tools": tools,
        "failure_modes": modes,
        "papers": papers,
        "taxonomies": taxonomies,
        "crosswalks": crosswalks,
        "incidents": incidents,
        "recipes": recipes,
    }
    tombstoned = _check_tombstones(err, live, data_dir)
    _check_manifest_lock(
        err,
        tools,
        modes,
        papers,
        taxonomies,
        crosswalks,
        incidents,
        recipes,
        tombstoned=tombstoned,
    )


def _check_tombstones(
    err: list[str], live: dict[str, dict[str, Any]], data_dir: Path
) -> dict[str, set[str]]:
    """Validate ``TOMBSTONES.yml`` (the list of removed nodes) and return
    the removed ids per kind. A removed id must not be in use again."""
    removed: dict[str, set[str]] = defaultdict(set)
    path = data_dir / "TOMBSTONES.yml"
    if not path.exists():
        return removed
    try:
        doc = load_yaml(path)
    except ValueError as exc:
        err.append(f"[tombstones] TOMBSTONES.yml :: <file> — {exc}")
        return removed
    entries = doc.get("tombstones")
    if not isinstance(entries, list):
        err.append("[tombstones] TOMBSTONES.yml :: tombstones — must be a list")
        return removed
    for index, entry in enumerate(entries):
        where = f"[tombstones] TOMBSTONES.yml :: tombstones/{index}"
        if not isinstance(entry, dict):
            err.append(f"{where} — must be a mapping")
            continue
        node_id, kind = entry.get("id"), TOMBSTONE_KINDS.get(str(entry.get("kind")))
        if not isinstance(node_id, str) or not node_id:
            err.append(f"{where} — 'id' is missing")
            continue
        if kind is None:
            err.append(
                f"{where} — kind '{entry.get('kind')}' is not one of"
                f" {', '.join(TOMBSTONE_KINDS)}"
            )
            continue
        if _parse_date(entry.get("removed_on")) is None:
            err.append(f"{where} — 'removed_on' must be a date")
        if not str(entry.get("reason") or "").strip():
            err.append(f"{where} — 'reason' is missing")
        if node_id in removed[kind]:
            err.append(f"{where} — {entry.get('kind')} '{node_id}' is listed twice")
        removed[kind].add(node_id)
        if node_id in live.get(kind, {}):
            err.append(
                f"{where} — {entry.get('kind')} '{node_id}' has a tombstone but"
                f" data/{kind}/{node_id}.yml exists; a removed id is never reused"
            )
        successor = entry.get("successor")
        if isinstance(successor, str) and successor not in live.get(kind, {}):
            err.append(
                f"{where} — successor '{successor}' is not a node in data/{kind}/"
            )
    return removed


def side_file_errors(nodes: Nodes, data_dir: Path | None = None) -> list[str]:
    """Checks on the two hand-kept files beside the node folders:
    ``failure_mode_priorities.yml`` and ``failure_mode_synonyms.yml``."""
    data_dir = data_dir or DATA_DIR
    errors: list[str] = []
    paper_ids = {
        n.get("id") for _, n in nodes.get("papers", []) if isinstance(n.get("id"), str)
    }

    def read(name: str) -> dict[str, Any] | None:
        path = data_dir / name
        if not path.exists():
            return None
        try:
            return load_yaml(path)
        except ValueError as exc:
            errors.append(f"[{name}] <file> — {exc}")
            return None

    prio = read("failure_mode_priorities.yml")
    if prio is not None:
        table = prio.get("priorities")
        if not isinstance(table, dict):
            errors.append(
                "[failure_mode_priorities.yml] priorities — must be a mapping"
            )
            table = {}
        for key in table:
            if key not in KNOWN_FAILURE_MODE_IDS:
                errors.append(
                    f"[failure_mode_priorities.yml] priorities/{key} — unknown"
                    " FailureMode"
                )
        for mode_id in sorted(KNOWN_FAILURE_MODE_IDS - set(table)):
            errors.append(
                f"[failure_mode_priorities.yml] priorities — no entry for"
                f" '{mode_id}'; it would be ranked with weight 0"
            )
        ordering = prio.get("expected_priority_ordering")
        for key in ordering if isinstance(ordering, list) else []:
            if key not in KNOWN_FAILURE_MODE_IDS:
                errors.append(
                    f"[failure_mode_priorities.yml] expected_priority_ordering —"
                    f" unknown FailureMode '{key}'"
                )

    syn = read("failure_mode_synonyms.yml")
    if syn is not None:
        blocks = syn.get("failure_modes") if "failure_modes" in syn else syn
        for key, block in (blocks or {}).items():
            if key in ("version", "last_updated", "notes", "status"):
                continue
            if not isinstance(block, dict):
                continue
            if key not in KNOWN_FAILURE_MODE_IDS:
                errors.append(
                    f"[failure_mode_synonyms.yml] {key} — unknown FailureMode"
                )
            for pid in _strs(block.get("anchor_papers")):
                if pid not in paper_ids:
                    errors.append(
                        f"[failure_mode_synonyms.yml] {key}/anchor_papers —"
                        f" missing paper '{pid}'"
                    )
    return errors


def _check_manifest_lock(
    err: list[str],
    tools: dict[str, Any],
    modes: dict[str, Any],
    papers: dict[str, Any],
    taxonomies: dict[str, Any],
    crosswalks: dict[str, Any],
    incidents: dict[str, Any] | None = None,
    recipes: dict[str, Any] | None = None,
    *,
    tombstoned: dict[str, set[str]] | None = None,
) -> None:
    """If ``data/MANIFEST.json`` exists, every id it declares must still be
    present in the current corpus or be listed in ``data/TOMBSTONES.yml``.
    This is the "external citations stay honest" guarantee — a rename
    shows up as ``old_id`` missing even if ``new_id`` has been added. The
    deeper contents of the manifest (count totals, URLs) are enforced by
    ``validator/generate_manifest.py --check`` in CI; here we only check id
    membership so local ``validator/cli.py`` runs stay useful even when the
    manifest is one commit behind.
    """
    if not MANIFEST_PATH.exists():
        return
    try:
        manifest = json.loads(MANIFEST_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        err.append(f"[manifest] data/MANIFEST.json is unreadable: {exc}")
        return

    declared = manifest.get("ids", {}) if isinstance(manifest, dict) else {}
    current = {
        "tools": set(tools.keys()),
        "failure_modes": set(modes.keys()),
        "papers": set(papers.keys()),
        "taxonomies": set(taxonomies.keys()),
        "crosswalks": set(crosswalks.keys()),
        "incidents": set((incidents or {}).keys()),
        "recipes": set((recipes or {}).keys()),
    }
    for kind, live_ids in current.items():
        entry = declared.get(kind)
        if isinstance(entry, dict):
            declared_ids = set(entry.keys())
        elif isinstance(entry, list):
            declared_ids = set(entry)
        else:
            declared_ids = set()
        missing = declared_ids - live_ids - (tombstoned or {}).get(kind, set())
        for mid in sorted(missing):
            err.append(
                f"[manifest] {kind} id '{mid}' is in MANIFEST.json but no longer "
                f"present in data/{kind}/ — renames and deletions break external "
                f"citations. Restore the node, or record the removal in "
                f"data/TOMBSTONES.yml (id, kind, removed_on, reason)."
            )


def has_cycle(edges: list[tuple[str, str]]) -> bool:
    graph: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        graph[a].append(b)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(int)

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for n in graph[node]:
            if color[n] == GRAY:
                return True
            if color[n] == WHITE and dfs(n):
                return True
        color[node] = BLACK
        return False

    return any(color[n] == WHITE and dfs(n) for n in list(graph))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    global DATA_DIR, MANIFEST_PATH

    ap = argparse.ArgumentParser(
        description="Validate the SAICA-KG YAML files. Offline unless a network"
        " flag is given."
    )
    ap.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    ap.add_argument(
        "--only",
        default="",
        help="Comma-separated node kinds for the per-file schema pass"
        " (cross-file checks always run on everything)",
    )
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Validate this directory instead of the repository's data/",
    )
    ap.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Manifest to check ids against (default: <data-dir>/MANIFEST.json)",
    )
    ap.add_argument(
        "--as-of",
        type=dt.date.fromisoformat,
        default=None,
        help="Date used for 'in the future' checks (default: today)",
    )
    ap.add_argument(
        "--arxiv",
        action="store_true",
        help="Opt-in: compare paper titles and first authors, and arXiv links in"
        " incident sources, with arXiv records (cached in validator/cache/)",
    )
    ap.add_argument(
        "--links",
        action="store_true",
        help="Opt-in, network: check that source URLs still answer (cached)",
    )
    ap.add_argument(
        "--offline",
        action="store_true",
        help="With --arxiv / --links: use the caches only, never the network",
    )
    args = ap.parse_args(argv)

    saved = (DATA_DIR, MANIFEST_PATH)
    if args.data_dir is not None:
        DATA_DIR = args.data_dir.resolve()
        MANIFEST_PATH = DATA_DIR / "MANIFEST.json"
    if args.manifest is not None:
        MANIFEST_PATH = args.manifest.resolve()
    try:
        return _run(args)
    finally:
        DATA_DIR, MANIFEST_PATH = saved


def _run(args: argparse.Namespace) -> int:
    as_of = args.as_of or dt.date.today()
    kinds = (
        list(NODE_MODELS.keys())
        if not args.only
        else [k.strip() for k in args.only.split(",")]
    )
    errors: list[str] = []
    warnings: list[str] = []

    if not DATA_DIR.is_dir():
        print(f"ERROR data directory not found: {DATA_DIR}", file=sys.stderr)
        return 1

    nodes, load_errors = load_corpus(DATA_DIR)
    errors.extend(load_errors)

    for kind in kinds:
        if kind not in NODE_MODELS:
            errors.append(f"unknown kind '{kind}'")
            continue
        errors.extend(schema_errors(kind, nodes[kind], as_of=as_of))

    cross_invariants(warnings, errors, nodes, data_dir=DATA_DIR)
    errors.extend(side_file_errors(nodes, DATA_DIR))

    if args.arxiv or args.links:
        from validator import netchecks

        net_errors, net_warnings, net_notes = netchecks.run(
            nodes,
            arxiv=args.arxiv,
            links=args.links,
            offline=args.offline,
        )
        errors.extend(net_errors)
        warnings.extend(net_warnings)
        for note in net_notes:
            print(f"NOTE  {note}")

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)

    total_nodes = sum(len(v) for v in nodes.values())
    print(
        f"\nValidated {total_nodes} nodes: {len(errors)} errors, {len(warnings)} warnings"
    )

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

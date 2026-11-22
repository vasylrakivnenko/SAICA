"""One loader for the knowledge graph (``data/``) on the served surface.

Ask, Assess, the audit CLI, the SAICA Index, the MCP server and the
recommender all read ``data/`` through this module. Before it existed
there were five loaders with five different rules (review 2026-11-21,
H9): two keyed a node by its file name and three by its ``id``, two read
``.yaml`` files that the gate rejects, one skipped a broken file without a
word and one crashed on it, and the list of failure modes was typed out
in five places.

What this module guarantees:

* Every node is parsed into its model in :mod:`pipeline.models` with the
  same strict typing the gate (``validator/cli.py``) uses. Served code
  never works with a node whose shape the gate would refuse.
* Only ``*.yml`` files are read, ``id`` must equal the file name, and
  nodes come back sorted by id.
* One error policy. A file that cannot be read, writes a key twice, is
  not a mapping, fails its model or carries the wrong ``id`` is left out;
  one :class:`LoadError` is recorded and logged for it. ``strict=True``
  raises :class:`KGError` instead. Served code uses the default, so one
  broken file cannot take the site down. Tests use ``strict``.
* The list of failure modes comes from ``data/failure_modes/``
  (:meth:`KG.failure_mode_ids`). Nothing types the ids in again.

What it does not do: the cross-file checks (every reference resolves, no
node entered twice) stay in ``validator/cli.py``. ``data/TOMBSTONES.yml``
lists removed nodes; it is not a node and is not loaded here.

Each node is available in two forms: the validated model object
(``kg.tools["semgrep"]``) and the plain mapping that was validated
(``kg.tool_dicts()["semgrep"]``; JSON types, dates as ISO strings). The
mappings are shared between callers: treat them as read-only.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from pipeline.models import (
    Crosswalk,
    FailureMode,
    Incident,
    Paper,
    Recipe,
    Taxonomy,
    Tool,
)

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
PRIORITIES_FILE = "failure_mode_priorities.yml"

# Node kind -> (folder under data/, model). The kind is the singular name
# used in Ask citations and in ``data/TOMBSTONES.yml``. The order is the
# order in which :meth:`KG.find` looks an id up.
KINDS: dict[str, tuple[str, type[BaseModel]]] = {
    "tool": ("tools", Tool),
    "failure_mode": ("failure_modes", FailureMode),
    "taxonomy": ("taxonomies", Taxonomy),
    "paper": ("papers", Paper),
    "incident": ("incidents", Incident),
    "recipe": ("recipes", Recipe),
    "crosswalk": ("crosswalks", Crosswalk),
}

# Finish building the models now. ``Tool`` refers to a class defined after
# it, so pydantic would otherwise build its schema at the first validation,
# and a test that swaps ``datetime.date`` at that moment breaks the build.
for _folder, _model in KINDS.values():
    _model.model_rebuild()


@dataclass(frozen=True)
class LoadError:
    """One file that was left out of the KG, and why."""

    folder: str
    file: str
    message: str

    def __str__(self) -> str:
        return f"[{self.folder}] {self.file} — {self.message}"


class KGError(RuntimeError):
    """Raised by a strict load when at least one file was left out."""

    def __init__(self, errors: tuple[LoadError, ...]) -> None:
        self.errors = errors
        shown = "; ".join(str(e) for e in errors[:5])
        more = f" (and {len(errors) - 5} more)" if len(errors) > 5 else ""
        super().__init__(f"{len(errors)} KG file(s) could not be loaded: {shown}{more}")


# ---------------------------------------------------------------------------
# Reading one file (same rules as validator/cli.py)
# ---------------------------------------------------------------------------


class _UniqueKeyLoader(yaml.SafeLoader):
    """``yaml.SafeLoader`` that refuses a mapping with the same key twice.

    Plain PyYAML keeps the last value and says nothing.
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


def _json_typed(value: Any) -> Any:
    """YAML dates become ISO strings, as the JSON Schema expects."""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_typed(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_typed(v) for v in value]
    return value


def read_mapping(path: Path) -> dict[str, Any]:
    """Load one YAML file whose top level is a mapping.

    Raises ``ValueError`` with a one-line reason: unreadable, not YAML, a
    key written twice, or a top level that is not a mapping.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.load(
                fh, Loader=_UniqueKeyLoader
            )  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        raise ValueError(
            "cannot be read as YAML: " + " ".join(str(exc).split())
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot be read: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("top level must be a mapping")
    return _json_typed(data)


def _validate(model: type[BaseModel], raw: dict[str, Any]) -> BaseModel:
    """Parse ``raw`` into ``model``; ``ValueError`` with a short reason."""
    try:
        return model.model_validate_json(json.dumps(raw), strict=True)
    except ValidationError as exc:
        problems = exc.errors()
        first = problems[0]
        where = "/".join(str(part) for part in first.get("loc", ())) or "<root>"
        more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
        raise ValueError(f"{where}: {first.get('msg', 'invalid')}{more}") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cannot be checked against the schema: {exc}") from exc


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------


class KG:
    """A validated snapshot of one ``data/`` directory.

    Build it through :func:`load` (cached) rather than directly.
    """

    def __init__(self, data_dir: Path, *, strict: bool = False) -> None:
        self.data_dir = Path(data_dir)
        self._objects: dict[str, dict[str, BaseModel]] = {}
        self._dicts: dict[str, dict[str, dict[str, Any]]] = {}
        errors: list[LoadError] = []

        for kind, (folder, model) in KINDS.items():
            objects: dict[str, BaseModel] = {}
            dicts: dict[str, dict[str, Any]] = {}
            subdir = self.data_dir / folder
            if subdir.is_dir():
                for path in sorted(subdir.glob("*.yaml")):
                    errors.append(
                        LoadError(
                            folder,
                            path.name,
                            "not read: node files use the .yml extension",
                        )
                    )
                for path in sorted(subdir.glob("*.yml")):
                    try:
                        raw = read_mapping(path)
                        if raw.get("id") != path.stem:
                            raise ValueError(
                                f"id {raw.get('id')!r} does not equal the file name"
                            )
                        obj = _validate(model, raw)
                    except ValueError as exc:
                        errors.append(LoadError(folder, path.name, str(exc)))
                        continue
                    objects[path.stem] = obj
                    dicts[path.stem] = raw
            self._objects[kind] = objects
            self._dicts[kind] = dicts

        self._priorities = self._read_priorities(errors)
        self.errors: tuple[LoadError, ...] = tuple(errors)
        if strict and self.errors:
            raise KGError(self.errors)
        for error in self.errors:
            log.warning("KG file left out: %s", error)

    # -- nodes ---------------------------------------------------------------

    def nodes(self, kind: str) -> dict[str, BaseModel]:
        """``{id: model object}`` for one kind, sorted by id."""
        return dict(self._objects[kind])

    def dicts(self, kind: str) -> dict[str, dict[str, Any]]:
        """``{id: validated mapping}`` for one kind, sorted by id."""
        return dict(self._dicts[kind])

    @property
    def tools(self) -> dict[str, Tool]:
        return self.nodes("tool")  # type: ignore[return-value]

    @property
    def failure_modes(self) -> dict[str, FailureMode]:
        return self.nodes("failure_mode")  # type: ignore[return-value]

    def tool_dicts(self) -> dict[str, dict[str, Any]]:
        return self.dicts("tool")

    def find(self, node_id: str) -> tuple[str, dict[str, Any]] | None:
        """``(kind, validated mapping)`` for an id of any kind, or ``None``.

        Kinds are tried in the order of :data:`KINDS`.
        """
        for kind in KINDS:
            node = self._dicts[kind].get(node_id)
            if node is not None:
                return kind, node
        return None

    def ids(self) -> frozenset[str]:
        """Every node id of every kind."""
        return frozenset(i for nodes in self._dicts.values() for i in nodes)

    # -- failure modes -------------------------------------------------------

    def failure_mode_ids(self) -> tuple[str, ...]:
        """The failure-mode ids, as found in ``data/failure_modes/``, sorted."""
        return tuple(self._dicts["failure_mode"])

    def failure_mode_names(self) -> dict[str, str]:
        """``{id: display name}`` from each failure-mode file's ``name``."""
        return {
            fm_id: str(node.get("name") or fm_id)
            for fm_id, node in self._dicts["failure_mode"].items()
        }

    # -- priorities ----------------------------------------------------------

    def _read_priorities(self, errors: list[LoadError]) -> dict[str, dict[str, Any]]:
        path = self.data_dir / PRIORITIES_FILE
        try:
            doc = read_mapping(path)
        except ValueError as exc:
            errors.append(LoadError(".", PRIORITIES_FILE, str(exc)))
            return {}
        table = doc.get("priorities")
        if not isinstance(table, dict):
            errors.append(
                LoadError(".", PRIORITIES_FILE, "priorities: must be a mapping")
            )
            return {}
        out: dict[str, dict[str, Any]] = {}
        for fm_id, record in table.items():
            try:
                float(record["likelihood"])
                float(record["impact"])
            except (KeyError, TypeError, ValueError):
                errors.append(
                    LoadError(
                        ".",
                        PRIORITIES_FILE,
                        f"priorities/{fm_id}: needs numeric likelihood and impact",
                    )
                )
                continue
            out[str(fm_id)] = dict(record)
        return out

    def priority_records(self) -> dict[str, dict[str, Any]]:
        """The ``priorities`` table of ``failure_mode_priorities.yml``."""
        return {fm_id: dict(record) for fm_id, record in self._priorities.items()}

    def priorities(self) -> dict[str, float]:
        """``{failure mode id: likelihood × impact}``. Editorial weights."""
        return {
            fm_id: float(record["likelihood"]) * float(record["impact"])
            for fm_id, record in self._priorities.items()
        }


# ---------------------------------------------------------------------------
# The process-wide default
# ---------------------------------------------------------------------------

_lock = RLock()
_cache: dict[Path, KG] = {}
_override_dir: Path | None = None
_reset_hooks: list[Callable[[], None]] = []


def default_data_dir() -> Path:
    """The directory :func:`load` reads when none is given."""
    return _override_dir if _override_dir is not None else DATA_DIR


def load(data_dir: Path | None = None, *, strict: bool = False) -> KG:
    """The KG under ``data_dir`` (default: the repository's ``data/``).

    Parsed once per process and directory. Files changed on disk afterwards
    are not picked up until :func:`reset` or a restart.
    """
    key = Path(data_dir if data_dir is not None else default_data_dir()).resolve()
    with _lock:
        kg = _cache.get(key)
        if kg is None:
            kg = KG(key)
            _cache[key] = kg
    if strict and kg.errors:
        raise KGError(kg.errors)
    return kg


def on_reset(hook: Callable[[], None]) -> None:
    """Register a function that drops a cache derived from the KG."""
    if hook not in _reset_hooks:
        _reset_hooks.append(hook)


def reset() -> None:
    """Forget every parsed KG and every cache derived from one."""
    with _lock:
        _cache.clear()
    for hook in list(_reset_hooks):
        hook()


@contextmanager
def use_data_dir(data_dir: Path) -> Iterator[KG]:
    """Make another directory the default for the length of a ``with``.

    For tests and previews: every served module then reads the fixture.
    """
    global _override_dir
    previous = _override_dir
    _override_dir = Path(data_dir)
    reset()
    try:
        yield load()
    finally:
        _override_dir = previous
        reset()


# Short forms for the common reads.


def load_tools() -> dict[str, dict[str, Any]]:
    """``{tool id: validated mapping}`` of the default KG, sorted by id."""
    return load().tool_dicts()


def failure_mode_ids() -> tuple[str, ...]:
    """Failure-mode ids of the default KG (from ``data/failure_modes/``)."""
    return load().failure_mode_ids()


def load_priorities() -> dict[str, float]:
    """``{failure mode id: likelihood × impact}`` of the default KG."""
    return load().priorities()


__all__ = [
    "DATA_DIR",
    "KG",
    "KGError",
    "KINDS",
    "LoadError",
    "default_data_dir",
    "failure_mode_ids",
    "load",
    "load_priorities",
    "load_tools",
    "on_reset",
    "read_mapping",
    "reset",
    "use_data_dir",
]

"""Emit ``site/public/maturity.json`` so Astro pages can show each tool's
activity band without porting the scoring formula to JS.

Payload::

    {
      "version": 2,
      "as_of": "2026-11-21",          # date the recency facet is judged against
      "scale": {"name": "activity band", "description": "...", "bands": {"A": "...", ...}},
      "tools": {
        "<tool_id>": {
          "band":          "A" | "B" | "C" | "D" | "E" | "F",
          "computed_band": "...",       # before a curator override
          "score":         6.42,
          "facets":        {"stars": 1.9, "recent_push": 2.0, ...},
          "is_override":   false,
          "notes":         ["..."],
          "override":      null | {"tier": "...", "justification": "..."},
          "tier": "...", "computed_tier": "..."   # same values under the old key names
        }
      }
    }

``as_of`` is not today's date. It is the newest check date found in the
tool files (``last_reviewed``, ``stars_updated_at``, ``upstream_pushed_at``,
``last_updated``), so the output is a function of ``data/tools/`` alone and
``--check`` gives the same answer on every day. Pass ``--as-of`` to pin
another date.

CLI:
  python -m validator.generate_maturity                     # write site/public/maturity.json
  python -m validator.generate_maturity --check             # CI drift gate
  python -m validator.generate_maturity --out-dir /tmp/x    # write /tmp/x/maturity.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from pipeline.maturity.score import (
    BAND_MEANING,
    SCALE_DESCRIPTION,
    compute_maturity,
    effective_band,
    reference_date,
)

REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "data" / "tools"
DEFAULT_OUT = REPO / "site" / "public" / "maturity.json"


def _load_tools(tools_dir: Path) -> list[dict[str, Any]]:
    docs = []
    for yml in sorted(tools_dir.glob("*.yml")):
        doc = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
        if isinstance(doc, dict) and isinstance(doc.get("id"), str):
            docs.append(doc)
    return docs


def build_payload(
    *, as_of: date | None = None, tools_dir: Path | None = None
) -> dict[str, Any]:
    """Score every tool against ``as_of`` (default: the newest check date
    in the tool files)."""
    docs = _load_tools(tools_dir or TOOLS_DIR)
    if as_of is None:
        as_of = reference_date(docs)
    if as_of is None:
        raise SystemExit(
            "generate_maturity: no date found in the tool files to judge recency"
            " against; pass --as-of YYYY-MM-DD"
        )
    tools: dict[str, Any] = {}
    for doc in docs:
        score = compute_maturity(doc, as_of=as_of)
        band = effective_band(doc, as_of=as_of)
        override = doc.get("maturity_override")
        tools[doc["id"]] = {
            "band": band,
            "computed_band": score.band,
            "score": score.score,
            "facets": score.facets,
            "notes": score.notes,
            "is_override": bool(override),
            "override": override if isinstance(override, dict) else None,
            # Same values under the key names used before 2026-11-21.
            "tier": band,
            "computed_tier": score.band,
        }
    return {
        "version": 2,
        "as_of": as_of.isoformat(),
        "scale": {
            "name": "activity band",
            "description": SCALE_DESCRIPTION,
            "bands": BAND_MEANING,
        },
        "tools": tools,
    }


def _serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


def write_payload(out: Path, *, as_of: date | None = None) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_serialize(build_payload(as_of=as_of)), encoding="utf-8")


def check_payload(out: Path, *, as_of: date | None = None) -> int:
    expected = _serialize(build_payload(as_of=as_of))
    actual = out.read_text(encoding="utf-8") if out.exists() else ""
    if expected != actual:
        print(
            f"generate_maturity --check: {out} is out of date.\n"
            "Run `python -m validator.generate_maturity` and commit.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m validator.generate_maturity")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--out", type=Path, default=None, help="Output file.")
    target.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Write maturity.json into this directory instead of site/public/.",
    )
    parser.add_argument("--check", action="store_true", help="CI drift gate")
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="Judge recency against this date (default: newest check date in"
        " data/tools/).",
    )
    args = parser.parse_args(argv)
    out = args.out or (args.out_dir / "maturity.json" if args.out_dir else DEFAULT_OUT)
    if args.check:
        return check_payload(out, as_of=args.as_of)
    write_payload(out, as_of=args.as_of)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

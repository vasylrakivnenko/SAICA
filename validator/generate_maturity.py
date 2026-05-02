"""Emit ``site/public/maturity.json`` so Astro pages can render the
auto-computed maturity tier without porting the scoring formula to JS.

Per-tool payload::

    {
      "<tool_id>": {
        "tier":       "1A" | "1B" | "2A" | "2B" | "3" | "4",
        "score":      6.42,
        "facets":     {"paper_citations": 6.0, ...},
        "is_override": false,
        "notes":      ["..."],
        "override":   null | {"tier": "...", "justification": "..."}
      }
    }

CLI:
  python -m validator.generate_maturity            # write
  python -m validator.generate_maturity --check    # CI drift gate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from pipeline.maturity.score import compute_maturity, effective_tier

REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "data" / "tools"
DEFAULT_OUT = REPO / "site" / "public" / "maturity.json"


def build_payload() -> dict[str, Any]:
    tools: dict[str, Any] = {}
    for yml in sorted(TOOLS_DIR.glob("*.yml")):
        doc = yaml.safe_load(yml.read_text()) or {}
        tool_id = doc.get("id")
        if not isinstance(tool_id, str):
            continue
        score = compute_maturity(doc)
        override = doc.get("maturity_override")
        tools[tool_id] = {
            "tier": effective_tier(doc),
            "computed_tier": score.tier,
            "score": score.score,
            "facets": score.facets,
            "notes": score.notes,
            "is_override": bool(override),
            "override": override if isinstance(override, dict) else None,
        }
    return {"version": 1, "tools": tools}


def write_payload(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_payload(), indent=2, sort_keys=True) + "\n")


def check_payload(out: Path) -> int:
    expected = json.dumps(build_payload(), indent=2, sort_keys=True) + "\n"
    actual = out.read_text() if out.exists() else ""
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
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="CI drift gate")
    args = parser.parse_args(argv)
    if args.check:
        return check_payload(args.out)
    write_payload(args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

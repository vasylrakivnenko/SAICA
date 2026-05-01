"""CLI: regenerate SAICA-KG embeddings, UMAP projection, drift report.

Usage
-----

Regenerate everything (default)::

    python -m pipeline.cli.embed

Only write the drift report (skip projection + JSON export)::

    python -m pipeline.cli.embed --drift-only

Skip drift report (produce just embeddings + projection JSON)::

    python -m pipeline.cli.embed --no-drift

On first run the sentence-transformer model (~90 MB) is downloaded into
``.cache/st-models/`` — a one-time cost. Subsequent runs are offline.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from pipeline.embeddings.compute import (
    CACHE_DIR,
    compute_embeddings,
    save_store,
)
from pipeline.embeddings.drift_report import (
    compute_drift,
    write_report,
)
from pipeline.embeddings.umap_project import (
    EMBEDDINGS_JSON_PATH,
    project_all,
    write_embeddings_json,
)

log = logging.getLogger("pipeline.cli.embed")

EXIT_OK = 0
EXIT_FAIL = 1


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--drift-only",
        action="store_true",
        help="Skip JSON projection export; only write the drift report.",
    )
    p.add_argument(
        "--no-drift",
        action="store_true",
        help="Skip drift report.",
    )
    p.add_argument(
        "--top-n-drift",
        type=int,
        default=20,
        help="Number of tools to list in the drift report (default: 20).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    t0 = time.perf_counter()
    log.info("Computing embeddings…")
    store = compute_embeddings()
    log.info(
        "Encoded %d nodes (%d dim) in %.2fs",
        len(store.ids),
        store.vectors.shape[1],
        time.perf_counter() - t0,
    )
    save_store(store, CACHE_DIR)
    log.info("Cached vectors → %s", CACHE_DIR)

    if not args.drift_only:
        t1 = time.perf_counter()
        payload = project_all(store)
        out = write_embeddings_json(payload, EMBEDDINGS_JSON_PATH)
        size_kb = out.stat().st_size / 1024
        log.info(
            "Wrote projection JSON → %s (%.1f KB) in %.2fs",
            out,
            size_kb,
            time.perf_counter() - t1,
        )

    if not args.no_drift:
        t2 = time.perf_counter()
        tools_store = store.by_type("tool")
        rows = compute_drift(tools_store, top_n=args.top_n_drift)
        report_path = write_report(rows)
        log.info(
            "Wrote drift report → %s (%d rows) in %.2fs",
            report_path,
            len(rows),
            time.perf_counter() - t2,
        )

    log.info("Total time: %.2fs", time.perf_counter() - t0)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

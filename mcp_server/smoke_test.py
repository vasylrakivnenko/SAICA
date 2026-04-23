"""Smoke test — exercises each MCP tool's underlying logic without stdio transport."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.graph import Graph, envelope


def main() -> int:
    g = Graph.load()
    print("=== Loaded graph ===")
    print(f"  tools:         {len(g.tools)}")
    print(f"  failure_modes: {len(g.failure_modes)}")
    print(f"  papers:        {len(g.papers)}")
    print(f"  taxonomies:    {len(g.taxonomies)}")
    print(f"  crosswalks:    {len(g.crosswalks)}")

    print("\n=== Query 1: search tools for control_paradigm=prevention ===")
    results = g.search_tools(control_paradigm="prevention")
    for r in results:
        print(f"  {r['id']:25s}  {r['temporal_phase']:18s}  {r['autonomy_level']}")

    print("\n=== Query 2: search for tools addressing supply_chain_attack ===")
    results = g.search_tools(failure_mode="supply_chain_attack")
    for r in results:
        print(f"  {r['id']:25s}  {r['control_paradigm']:12s}  addresses {r['addresses_failure_modes']}")

    print("\n=== Query 3: explain supply_chain_attack ===")
    data = g.explain_failure_mode("supply_chain_attack")
    print(f"  name:              {data['name']}")
    print(f"  aliases:           {data['aliases']}")
    print(f"  detection_signals: {len(data['detection_signals'])}")
    print(f"  prior_work:        {[p.get('id') for p in data['prior_work']]}")
    print(f"  crosswalks:")
    for cw in data["crosswalks"]:
        print(f"    - {cw['taxonomy']}/{cw['external_id']} ({cw['confidence']}) -> {cw.get('external_label','')}")
    print(f"  mitigators: {[m['id'] for m in data['mitigators']]}")

    print("\n=== Query 4: snapshot counts ===")
    snap = g.snapshot()
    print(f"  kg_version:      {snap['kg_version']}")
    print(f"  kg_last_updated: {snap['kg_last_updated']}")
    print(f"  counts:          {snap['counts']}")

    print("\n=== Query 5: envelope shape for search ===")
    env = envelope(results=results, query={"failure_mode": "supply_chain_attack"}, ranking_criteria=["maturity_status"], total=len(results), g=g)
    assert set(env.keys()) == {"results", "ranking_criteria", "query_echo", "total_matched", "kg_version", "kg_last_updated", "disclaimer"}
    print(f"  envelope keys OK: {sorted(env.keys())}")
    print(f"  disclaimer:       {env['disclaimer'][:60]}...")

    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

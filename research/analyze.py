#!/usr/bin/env python3
"""Analyze Semantic Scholar raw results and surface the most relevant papers."""
import json
import os
import re
from collections import defaultdict

RAW_DIR = "/Users/vasyl/saicakg/research/s2_raw"

# Map slug -> theme bucket for grouping
THEME = {
    "supervising-ai-coding-agents": "supervision",
    "llm-code-failure-taxonomy": "failure_classes",
    "package-hallucination-slopsquatting": "failure_classes",
    "code-gen-hallucination-classification": "failure_classes",
    "kg-software-tools-taxonomy": "kg_approaches",
    "mece-classification-se": "mece_methods",
    "agent-control-paradigm-prevention-detection": "supervision",
    "code-reinvention-duplicate-detection-llm": "failure_classes",
    "self-debug-reflexion-coding-agent": "supervision",
    "sandboxed-execution-ai-code-agent": "supervision",
    "hitl-code-generation": "supervision",
    "mcp-evaluation": "benchmarks",
    "retrieval-augmented-code-generation": "supervision",
    "llm-code-guardrails-structured-output": "supervision",
    "software-supply-chain-llm-attack": "failure_classes",
    "agent-trajectory-supervision-monitoring": "supervision",
    "faceted-classification-kg-survey": "mece_methods",
    "deprecated-api-detection-llm": "failure_classes",
}

# Relevance signal keywords per theme
POSITIVE = [
    "llm", "large language model", "code generation", "coding agent", "software agent",
    "hallucination", "taxonomy", "classification", "supervision", "monitoring",
    "knowledge graph", "ontology", "mcp", "model context protocol", "faceted",
    "reflexion", "self-debug", "self-repair", "sandbox", "guardrail", "retrieval",
    "human-in-the-loop", "hitl", "agent", "reinvent", "duplicate", "supply chain",
    "slopsquat", "deprecated api", "api evolution", "failure", "benchmark",
    "evaluation", "verification", "trajectory", "autonomy", "copilot", "swe-bench",
    "structured output", "constrained decoding",
]
NEGATIVE = [
    "education", "classroom", "students", "teaching", "medical imaging",
    "biology", "chemistry", "clinical trial", "agriculture", "crop",
    "social media sentiment", "molecular", "genome", "robot arm",
]


def score(paper, query_slug):
    txt = " ".join([
        (paper.get("title") or ""),
        (paper.get("abstract") or ""),
        ((paper.get("tldr") or {}).get("text") or ""),
        (paper.get("venue") or ""),
    ]).lower()
    s = 0
    for kw in POSITIVE:
        if kw in txt:
            s += 2
    for kw in NEGATIVE:
        if kw in txt:
            s -= 3
    # recency boost
    y = paper.get("year") or 0
    if y >= 2024:
        s += 4
    elif y >= 2023:
        s += 3
    elif y >= 2022:
        s += 1
    elif y > 0 and y < 2018:
        s -= 2
    # citation sanity (log-ish)
    cc = paper.get("citationCount") or 0
    if cc >= 500:
        s += 3
    elif cc >= 100:
        s += 2
    elif cc >= 20:
        s += 1
    # theme-specific boosts
    theme = THEME.get(query_slug, "")
    if theme == "mece_methods" and ("facet" in txt or "mece" in txt or "taxonomy" in txt):
        s += 2
    if theme == "kg_approaches" and ("knowledge graph" in txt or "ontolog" in txt):
        s += 2
    if theme == "failure_classes" and ("taxonomy" in txt or "empirical study" in txt or "classification" in txt):
        s += 2
    if theme == "supervision" and ("agent" in txt or "supervis" in txt or "monitor" in txt):
        s += 1
    return s


def extract_author_names(paper):
    authors = paper.get("authors") or []
    return [a.get("name") for a in authors if a.get("name")]


def main():
    all_papers = {}  # paperId -> (paper, best_score, queries)
    for fn in sorted(os.listdir(RAW_DIR)):
        if not fn.endswith(".json"):
            continue
        slug = fn[:-5]
        with open(os.path.join(RAW_DIR, fn)) as f:
            try:
                data = json.load(f)
            except Exception as e:
                print(f"FAIL {fn}: {e}")
                continue
        papers = data.get("data") or []
        for p in papers:
            pid = p.get("paperId") or (p.get("externalIds") or {}).get("DOI") or p.get("title")
            if not pid:
                continue
            sc = score(p, slug)
            if pid in all_papers:
                prev_p, prev_sc, qs = all_papers[pid]
                qs.add(slug)
                if sc > prev_sc:
                    all_papers[pid] = (p, sc, qs)
                else:
                    all_papers[pid] = (prev_p, prev_sc, qs)
            else:
                all_papers[pid] = (p, sc, {slug})

    # Sort by score
    ranked = sorted(all_papers.values(), key=lambda t: t[1], reverse=True)

    # Write summary
    out_path = "/Users/vasyl/saicakg/research/s2_ranked.md"
    with open(out_path, "w") as f:
        f.write(f"# Ranked papers (top 80 of {len(ranked)})\n\n")
        for i, (p, sc, qs) in enumerate(ranked[:80]):
            title = p.get("title") or "Untitled"
            year = p.get("year") or "?"
            venue = p.get("venue") or ""
            cc = p.get("citationCount") or 0
            url = p.get("url") or ""
            authors = ", ".join(extract_author_names(p)[:5])
            tldr = ((p.get("tldr") or {}).get("text") or "").strip()
            abstract = (p.get("abstract") or "").strip()
            theme_set = {THEME.get(q, "?") for q in qs}
            f.write(f"## {i+1}. [{sc}] {title} ({year})\n")
            f.write(f"- Authors: {authors}\n")
            f.write(f"- Venue: {venue} | Citations: {cc}\n")
            f.write(f"- URL: {url}\n")
            f.write(f"- Queries: {', '.join(sorted(qs))}\n")
            f.write(f"- Themes: {', '.join(sorted(theme_set))}\n")
            if tldr:
                f.write(f"- TLDR: {tldr}\n")
            elif abstract:
                f.write(f"- Abstract: {abstract[:400]}...\n")
            f.write("\n")
    print(f"Wrote {out_path}")
    print(f"Total unique papers: {len(all_papers)}")
    # Also dump top authors (candidate co-authors)
    author_counts = defaultdict(lambda: {"count": 0, "papers": [], "score": 0})
    for p, sc, qs in ranked[:120]:
        for a in extract_author_names(p):
            author_counts[a]["count"] += 1
            author_counts[a]["score"] += sc
            author_counts[a]["papers"].append(p.get("title"))
    top_authors = sorted(author_counts.items(), key=lambda kv: (kv[1]["score"], kv[1]["count"]), reverse=True)[:40]
    print("\nTop authors by aggregate relevance score (from top-120 papers):")
    for name, info in top_authors:
        print(f"  {name}: score={info['score']} papers={info['count']}")


if __name__ == "__main__":
    main()

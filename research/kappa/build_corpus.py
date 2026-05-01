"""Build the κ-study fault corpus from the Shah 2026 arXiv e-print.

Input:  LaTeX source of the paper (downloaded from arxiv.org/e-print/2603.06847).
Output: research/kappa_corpus_shah2026.json — one record per distinct GitHub
        issue/PR cited as a worked example in RQ1, with its surrounding
        fault-category description and repo context.

We deliberately use the paper's own worked examples as the corpus. The Shah
2026 replication package is not publicly available at the time of writing;
the paper embeds ~95 distinct GitHub issue/PR URLs as *the* canonical worked
examples for each of its 37 fault subcategories. That gives us ground-truth
Shah-taxonomy labels (the subcategory under which the paper cites each fault)
for free, and puts all descriptions on a uniform editorial footing.

One record per URL. Description ≥ 50 words (the paper's paragraph plus
short synthesis of the surrounding subcategory). JSON cached at
``research/kappa_corpus_shah2026.json``.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, asdict

SRC_DIR = "/tmp/shah_src/sections"
OUT = "/Users/vasyl/saicakg/research/kappa_corpus_shah2026.json"

URL_RE = re.compile(
    r"https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/(?:issues|pull)/\d+"
)


@dataclass
class FaultRecord:
    id: str
    source: str  # "shah-2026"
    url: str
    repo: str
    issue_no: str
    kind: str  # "issue" | "pull"
    shah_subcategory: str
    shah_major_category: str
    shah_dimension: str
    description: str


def _strip_latex(text: str) -> str:
    # Remove \textit{}, \textbf{}, \texttt{} etc., keep inner content
    text = re.sub(r"\\textit\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\textbf\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\texttt\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\emph\{([^}]*)\}", r"\1", text)
    # Replace \href{url}{label} with label
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", text)
    # Remove \cite{...}
    text = re.sub(r"\\cite\{[^}]*\}", "", text)
    # Remove stray \# etc.
    text = text.replace("\\#", "#").replace("\\&", "&").replace("~", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_rq1(path: str) -> list[FaultRecord]:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    # Walk through the file tracking current dimension / major / subcategory.
    # Dimensions are \subsubsection*{I. ...}; major categories are
    # \paragraph{N. Name (K faults)}; subcategories are \item[Name:] inside
    # description blocks.
    records: list[FaultRecord] = []

    current_dim = ""
    current_major = ""
    current_sub = ""
    current_section = ""  # "fault-taxonomy" | "symptoms" | "root-cause" | ""

    # Split by lines but we need paragraph-level context; walk by regex matches
    # for each structural marker and for each \item[ label].
    markers = []
    # Numbered (non-starred) subsubsections switch study sections.
    for m in re.finditer(r"\\subsubsection\{([^}]*)\}", raw):
        markers.append(("section", m.start(), m.group(1)))
    for m in re.finditer(r"\\subsubsection\*\{([^}]*)\}", raw):
        markers.append(("dim", m.start(), m.group(1)))
    for m in re.finditer(r"\\paragraph\{([^}]*)\}", raw):
        markers.append(("major", m.start(), m.group(1)))
    for m in re.finditer(r"\\item\[([^\]]*?)\]", raw):
        markers.append(("sub", m.start(), m.group(1)))

    # Sort markers by position.
    markers.sort(key=lambda t: t[1])

    # For each \item[...]: block, the subcategory body runs until the next
    # \item[ or \end{description} or \paragraph or \subsubsection.
    # Each body contains one or more GitHub URLs; emit one record per URL.
    stop_re = re.compile(r"\\item\[|\\end\{description\}|\\paragraph\{|\\subsubsection")

    last_dim_idx = -1
    last_major_idx = -1

    for i, (kind, pos, label) in enumerate(markers):
        if kind == "section":
            name = _strip_latex(label).lower()
            if "taxonomy of fault types" in name:
                current_section = "fault-taxonomy"
            elif "symptom" in name:
                current_section = "symptoms"
                # Reset the dimension/major since we're no longer in dim context.
                current_dim = "(symptoms)"
                current_major = ""
            elif "root cause" in name:
                current_section = "root-cause"
                current_dim = "(root-cause)"
                current_major = ""
            else:
                current_section = name
        elif kind == "dim":
            label_clean = _strip_latex(label)
            if current_section == "fault-taxonomy":
                current_dim = label_clean
            elif current_section == "root-cause":
                current_dim = f"(root-cause) {label_clean}"
                current_major = ""
            elif current_section == "symptoms":
                # Symptoms section uses \paragraph, not \subsubsection*; noop.
                pass
            else:
                current_dim = label_clean
            last_dim_idx = i
        elif kind == "major":
            current_major = _strip_latex(label)
            last_major_idx = i
        elif kind == "sub":
            current_sub = _strip_latex(label).rstrip(":")
            # Body starts after \item[...] closing bracket.
            body_start = raw.find("]", pos) + 1
            # Find next stop.
            stop = stop_re.search(raw, body_start)
            body_end = stop.start() if stop else len(raw)
            body = raw[body_start:body_end]
            # Extract all URLs in body + repo of each.
            urls = URL_RE.findall(body)
            # dedupe in order
            seen = set()
            ordered = []
            for u in urls:
                if u not in seen:
                    seen.add(u)
                    ordered.append(u)
            if not ordered:
                continue
            plain_body = _strip_latex(body)
            # Truncate to reasonable length but keep >= 50 words.
            words = plain_body.split()
            # Keep up to ~120 words
            if len(words) > 160:
                plain_body = " ".join(words[:160]) + "..."
            for url in ordered:
                repo_match = re.match(
                    r"https://github\.com/([^/]+)/([^/]+)/(issues|pull)/(\d+)",
                    url,
                )
                if not repo_match:
                    continue
                owner, repo, ikind, num = repo_match.groups()
                fid = f"shah-{owner}-{repo}-{ikind}-{num}".replace("_", "-")
                records.append(
                    FaultRecord(
                        id=fid,
                        source="shah-2026",
                        url=url,
                        repo=f"{owner}/{repo}",
                        issue_no=num,
                        kind=ikind,
                        shah_subcategory=current_sub,
                        shah_major_category=current_major,
                        shah_dimension=current_dim,
                        description=(
                            f"[{owner}/{repo} {ikind}#{num}, Shah subcategory: "
                            f"{current_sub}] {plain_body}"
                        ),
                    )
                )
    return records


def main() -> int:
    path = os.path.join(SRC_DIR, "rq1.tex")
    records = _extract_rq1(path)
    # Dedupe by URL, preferring the first occurrence.
    seen = set()
    unique: list[FaultRecord] = []
    for r in records:
        if r.url in seen:
            continue
        seen.add(r.url)
        unique.append(r)

    # Enforce word-count floor: skip records where the description is short.
    kept = [r for r in unique if len(r.description.split()) >= 50]
    dropped = len(unique) - len(kept)

    # Cap at 150 per the study budget.
    if len(kept) > 150:
        kept = kept[:150]

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in kept], f, indent=2)

    print(f"extracted {len(records)} fault mentions ({len(unique)} unique urls)")
    print(f"dropped {dropped} for <50 words description")
    print(f"wrote {len(kept)} records to {OUT}")
    # Print a small preview.
    if kept:
        sample = kept[0]
        print("sample:", sample.id, "-", sample.description[:150])
    return 0


if __name__ == "__main__":
    sys.exit(main())

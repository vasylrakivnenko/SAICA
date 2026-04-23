// KGGraph.ts — Cytoscape.js-powered knowledge-graph visualization for SAICA-KG.
// Runtime: fetches /api/v1/snapshot.json and renders into #cy.
import cytoscape from "cytoscape";
import type { Core, ElementDefinition, LayoutOptions, NodeSingular, EventObjectNode, Stylesheet } from "cytoscape";

// ---------- Types ----------
interface Tool {
  id: string; name: string;
  control_paradigm?: string; temporal_phase?: string; autonomy_level?: string;
  addresses_failure_modes?: string[]; composes_with?: string[]; feeds_into?: string[];
  supersedes?: string[]; cited_in?: string[]; documented_in?: string[];
  stars?: number | null; stars_updated_at?: string | null;
}
interface Crosswalk { taxonomy: string; external_id: string; confidence?: string; }
interface FailureMode {
  id: string; name: string; description?: string;
  prior_work?: string[]; crosswalks?: Crosswalk[];
}
interface Paper { id: string; title?: string; authors?: string | string[]; year?: number | string; venue?: string; }
interface Taxonomy { id: string; name: string; owner?: string; categories?: { external_id: string; label: string }[]; }
interface Snapshot {
  kg_version?: string; kg_last_updated?: string; counts?: Record<string, number>; disclaimer?: string;
  nodes: {
    tools?: Record<string, Tool>;
    failure_modes?: Record<string, FailureMode>;
    papers?: Record<string, Paper>;
    taxonomies?: Record<string, Taxonomy>;
    crosswalks?: unknown;
  };
}
type NodeType = "tool" | "failure_mode" | "taxonomy" | "paper";
type EdgeType = "addresses" | "composes_with" | "feeds_into" | "supersedes" | "crosswalks" | "prior_work" | "cited_in";

// ---------- Style tokens ----------
const TYPE_COLOR: Record<NodeType, string> = {
  tool: "#4f46e5", failure_mode: "#f43f5e", taxonomy: "#a855f7", paper: "#94a3b8",
};
const PARADIGM_BORDER: Record<string, string> = {
  prevention: "#10b981", detection: "#f59e0b", correction: "#ec4899", recovery: "#06b6d4",
};
const EDGE_STYLE: Record<EdgeType, { color: string; line?: "solid" | "dashed" | "dotted" }> = {
  addresses:     { color: "#fb7185" },
  composes_with: { color: "#818cf8", line: "dashed" },
  feeds_into:    { color: "#818cf8" },
  supersedes:    { color: "#22d3ee", line: "dotted" },
  crosswalks:    { color: "#c084fc" },
  prior_work:    { color: "#cbd5e1", line: "dashed" },
  cited_in:      { color: "#e2e8f0", line: "dotted" },
};

let cy: Core | null = null;
let snapshotRef: Snapshot | null = null;

export async function mountKGGraph(opts: {
  container: HTMLElement; sidebar: HTMLElement; filters: HTMLElement;
  layoutSelect: HTMLSelectElement; resetBtn: HTMLButtonElement;
  search: HTMLInputElement; focusNodeId?: string | null;
}): Promise<void> {
  const { container, sidebar, filters, layoutSelect, resetBtn, search, focusNodeId } = opts;

  let snapshot: Snapshot;
  try {
    const res = await fetch("/api/v1/snapshot.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    snapshot = (await res.json()) as Snapshot;
  } catch (err) {
    container.innerHTML = `<div style="padding:24px;font-size:14px;color:#991b1b;background:#fef2f2;border-radius:6px">
      Could not load knowledge graph data: ${escapeHtml(String(err))}.
      See <a href="/api/v1/snapshot.json">/api/v1/snapshot.json</a>.</div>`;
    return;
  }
  snapshotRef = snapshot;

  const { elements, nodeCount } = buildElements(snapshot);
  const heavyGraph = nodeCount > 200;

  // Build per-edge-type selectors from EDGE_STYLE.
  const edgeStyleBlocks = (Object.keys(EDGE_STYLE) as EdgeType[]).map((et) => {
    const s = EDGE_STYLE[et];
    const style: Record<string, unknown> = {
      "line-color": s.color, "target-arrow-color": s.color,
    };
    if (s.line) style["line-style"] = s.line;
    if (et === "crosswalks") style.label = "data(confidence)";
    return { selector: `edge[etype = "${et}"]`, style };
  });

  cy = cytoscape({
    container, elements,
    wheelSensitivity: 0.2, minZoom: 0.1, maxZoom: 4,
    style: [
      {
        selector: "node",
        style: {
          label: "data(label)",
          "font-size": 11, "font-weight": 500,
          "text-valign": "bottom", "text-halign": "center", "text-margin-y": 6,
          "text-wrap": "ellipsis", "text-max-width": "140px",
          color: "#334155",
          "background-color": (n: NodeSingular) => TYPE_COLOR[n.data("type") as NodeType] || "#94a3b8",
          "background-opacity": 0.92,
          "border-width": 1.5,
          "border-color": (n: NodeSingular) => {
            const p = n.data("control_paradigm");
            return (p && PARADIGM_BORDER[p]) || "#64748b";
          },
          "border-opacity": 0.9,
          width: 22, height: 22,
        },
      },
      {
        selector: 'node[type = "tool"]',
        style: {
          shape: "round-rectangle",
          // Log-scaled by GitHub stars; square aspect. Pre-computed in buildElements.
          width: (n: NodeSingular) => Number(n.data("toolSize")) || 18,
          height: (n: NodeSingular) => Number(n.data("toolSize")) || 18,
        },
      },
      { selector: 'node[type = "failure_mode"]', style: { shape: "diamond", width: 28, height: 28 } },
      { selector: 'node[type = "taxonomy"]', style: { shape: "hexagon", width: 30, height: 30 } },
      {
        selector: 'node[type = "paper"]',
        style: {
          shape: "ellipse", width: 12, height: 12,
          "font-size": 9, color: "#94a3b8",
          "text-max-width": "110px",
        },
      },
      {
        selector: "node:selected",
        style: {
          "border-color": "#f59e0b", "border-width": 3, "border-opacity": 1,
          "background-opacity": 1,
        },
      },
      {
        selector: "edge",
        style: {
          width: 1, "line-color": "#cbd5e1", "target-arrow-color": "#cbd5e1",
          "target-arrow-shape": "triangle", "arrow-scale": 0.75,
          "curve-style": "bezier", opacity: 0.75,
          "font-size": 8, color: "#94a3b8", "text-rotation": "autorotate",
          "text-background-color": "#ffffff", "text-background-opacity": 0.9,
          "text-background-padding": "2px", "text-background-shape": "round-rectangle",
        },
      },
      { selector: "edge:selected", style: { width: 2, opacity: 1 } },
      // Focus pattern: when a node is selected (via click or search), its
      // 1-hop neighborhood stays at normal visibility; everything else fades.
      { selector: "node.kg-dim", style: { opacity: 0.12, "text-opacity": 0.12 } },
      { selector: "edge.kg-dim", style: { opacity: 0.06, "text-opacity": 0.06 } },
      { selector: "node.kg-neighbor", style: { "border-width": 2, "border-color": "#f59e0b", "border-opacity": 0.7 } },
      { selector: "edge.kg-neighbor", style: { width: 1.6, opacity: 1 } },
      ...edgeStyleBlocks,
    ] as unknown as Stylesheet[],
    layout: layoutFor("cose"),
  });

  if (heavyGraph) {
    cy.edges('[etype = "cited_in"]').style("display", "none");
    const ck = filters.querySelector<HTMLInputElement>('input[name="edge-cited_in"]');
    if (ck) ck.checked = false;
  }

  // ----- Focus / dim state -----
  // One or more "focus" nodes (from click or search match) keep their
  // 1-hop neighborhood at full visibility; everything else is dimmed.
  let clickFocusId: string | null = null;

  const computeFocusIds = (): Set<string> => {
    const ids = new Set<string>();
    if (clickFocusId) ids.add(clickFocusId);
    const q = (search.value || "").trim().toLowerCase();
    if (q && cy) {
      cy.nodes().forEach((n) => {
        if (n.style("display") === "none") return;
        const hay = `${n.data("label") || ""} ${n.id()}`.toLowerCase();
        if (hay.includes(q)) ids.add(n.id());
      });
    }
    return ids;
  };

  const applyFocus = () => {
    if (!cy) return;
    cy.elements().removeClass("kg-dim").removeClass("kg-neighbor");
    const ids = computeFocusIds();
    if (ids.size === 0) return;
    const focusNodes = cy.nodes().filter((n) => ids.has(n.id()));
    // closedNeighborhood = focus nodes + direct neighbors + connecting edges.
    const neighborhood = focusNodes.closedNeighborhood();
    const others = cy.elements().difference(neighborhood);
    others.addClass("kg-dim");
    // Emphasize the edges + neighbor nodes that belong to the focus cluster
    // (but not the focus nodes themselves — they already get node:selected).
    const neighborOnly = neighborhood.difference(focusNodes);
    neighborOnly.addClass("kg-neighbor");
  };

  cy.on("tap", "node", (evt: EventObjectNode) => {
    cy!.nodes().unselect();
    evt.target.select();
    clickFocusId = evt.target.id();
    applyFocus();
    renderSidebar(sidebar, evt.target);
  });
  cy.on("tap", (evt) => {
    if (evt.target === cy) {
      cy!.nodes().unselect();
      clickFocusId = null;
      applyFocus();
      renderSidebarEmpty(sidebar);
    }
  });

  layoutSelect.addEventListener("change", () => cy!.layout(layoutFor(layoutSelect.value)).run());
  resetBtn.addEventListener("click", () => {
    clickFocusId = null;
    search.value = "";
    applyFilters(filters, "");
    applyFocus();
    cy!.layout(layoutFor(layoutSelect.value)).run();
    cy!.fit(undefined, 30);
    cy!.nodes().unselect();
    renderSidebarEmpty(sidebar);
  });
  filters.addEventListener("change", () => { applyFilters(filters, search.value); applyFocus(); });
  search.addEventListener("input", () => { applyFilters(filters, search.value); applyFocus(); });

  if (focusNodeId) {
    const n = cy.getElementById(focusNodeId);
    if (n && n.nonempty()) {
      cy.one("layoutstop", () => {
        cy!.animate({ center: { eles: n }, zoom: 1.4 }, { duration: 400 });
        n.select();
        clickFocusId = n.id();
        applyFocus();
        renderSidebar(sidebar, n as NodeSingular);
      });
    }
  }

  renderSidebarEmpty(sidebar);
}

// ---------- Element construction ----------
function buildElements(s: Snapshot): { elements: ElementDefinition[]; nodeCount: number } {
  const elements: ElementDefinition[] = [];
  const tools = s.nodes.tools ?? {};
  const fms = s.nodes.failure_modes ?? {};
  const taxos = s.nodes.taxonomies ?? {};
  const papers = s.nodes.papers ?? {};

  const usedPaperIds = new Set<string>();
  for (const t of Object.values(tools)) {
    for (const p of t.cited_in ?? []) usedPaperIds.add(p);
    for (const p of t.documented_in ?? []) usedPaperIds.add(p);
  }
  for (const fm of Object.values(fms)) for (const p of fm.prior_work ?? []) usedPaperIds.add(p);

  for (const t of Object.values(tools)) {
    const stars = typeof t.stars === "number" ? t.stars : null;
    elements.push({ data: {
      id: t.id, type: "tool", label: t.name || t.id,
      control_paradigm: t.control_paradigm ?? null,
      temporal_phase: t.temporal_phase ?? null,
      autonomy_level: t.autonomy_level ?? null,
      stars,
      // Pre-computed Tool node size: sqrt(max(stars, 0) + 1) * 8, clamped to
      // [24, 80]. Tools without a stars count get the minimum size.
      toolSize: toolSizeFromStars(stars),
    }});
  }
  for (const fm of Object.values(fms)) elements.push({ data: { id: fm.id, type: "failure_mode", label: fm.name || fm.id } });
  for (const tx of Object.values(taxos)) elements.push({ data: { id: tx.id, type: "taxonomy", label: tx.name || tx.id } });
  for (const pid of usedPaperIds) {
    const p = papers[pid];
    if (p) elements.push({ data: { id: p.id, type: "paper", label: shortPaperLabel(p) } });
  }

  const seen = new Set<string>();
  const addEdge = (source: string, target: string, etype: EdgeType, extra: Record<string, unknown> = {}) => {
    const id = `${source}__${etype}__${target}`;
    if (seen.has(id)) return;
    seen.add(id);
    elements.push({ data: { id, source, target, etype, ...extra } });
  };

  for (const t of Object.values(tools)) {
    for (const fmId of t.addresses_failure_modes ?? []) if (fms[fmId]) addEdge(t.id, fmId, "addresses");
    for (const o of t.composes_with ?? []) if (tools[o]) addEdge(t.id, o, "composes_with");
    for (const o of t.feeds_into ?? []) if (tools[o]) addEdge(t.id, o, "feeds_into");
    for (const o of t.supersedes ?? []) if (tools[o]) addEdge(t.id, o, "supersedes");
    for (const pid of t.cited_in ?? []) if (papers[pid]) addEdge(t.id, pid, "cited_in");
  }
  for (const fm of Object.values(fms)) {
    for (const cw of fm.crosswalks ?? []) {
      if (taxos[cw.taxonomy]) addEdge(fm.id, cw.taxonomy, "crosswalks", {
        confidence: cw.confidence ?? "", external_id: cw.external_id,
      });
    }
    for (const pid of fm.prior_work ?? []) if (papers[pid]) addEdge(fm.id, pid, "prior_work");
  }

  return { elements, nodeCount: elements.filter((e) => !(e.data as any).source).length };
}

// ---------- Layouts ----------
function layoutFor(name: string): LayoutOptions {
  switch (name) {
    case "grid":         return { name: "grid", padding: 30, animate: true } as LayoutOptions;
    case "circle":       return { name: "circle", padding: 30, animate: true } as LayoutOptions;
    case "breadthfirst": return { name: "breadthfirst", directed: true, padding: 30, spacingFactor: 1.2, animate: true } as LayoutOptions;
    case "cose":
    default:
      return {
        name: "cose", animate: false, padding: 60,
        nodeRepulsion: () => 18000, idealEdgeLength: () => 140,
        edgeElasticity: () => 120,
        gravity: 0.35, numIter: 1400, randomize: true,
        componentSpacing: 90,
      } as unknown as LayoutOptions;
  }
}

// ---------- Filters ----------
// Filters (type checkboxes, facet dropdowns, edge-type checkboxes) HIDE
// nodes/edges entirely. Search is NOT a filter — it drives the focus/dim
// system (see applyFocus in mountKGGraph) so that a matched node still
// shows its neighborhood.
function applyFilters(filters: HTMLElement, _query: string): void {
  if (!cy) return;
  const typeChecks: Record<string, boolean> = {};
  for (const t of ["tool", "failure_mode", "taxonomy", "paper"]) {
    const el = filters.querySelector<HTMLInputElement>(`input[name="type-${t}"]`);
    typeChecks[t] = el ? el.checked : true;
  }
  const edgeChecks: Record<string, boolean> = {};
  for (const et of Object.keys(EDGE_STYLE)) {
    const el = filters.querySelector<HTMLInputElement>(`input[name="edge-${et}"]`);
    edgeChecks[et] = el ? el.checked : true;
  }
  const paradigm = (filters.querySelector<HTMLSelectElement>('select[name="control_paradigm"]')?.value || "").trim();
  const phase = (filters.querySelector<HTMLSelectElement>('select[name="temporal_phase"]')?.value || "").trim();
  const autonomy = (filters.querySelector<HTMLSelectElement>('select[name="autonomy_level"]')?.value || "").trim();

  cy.batch(() => {
    cy!.nodes().forEach((n) => {
      const t = n.data("type") as string;
      let vis = !!typeChecks[t];
      if (vis && t === "tool") {
        if (paradigm && n.data("control_paradigm") !== paradigm) vis = false;
        if (vis && phase && n.data("temporal_phase") !== phase) vis = false;
        if (vis && autonomy && n.data("autonomy_level") !== autonomy) vis = false;
      }
      n.style("display", vis ? "element" : "none");
    });
    cy!.edges().forEach((e) => {
      const et = e.data("etype") as string;
      const typeOk = !!edgeChecks[et];
      const endpointsVisible = e.source().style("display") !== "none" && e.target().style("display") !== "none";
      e.style("display", typeOk && endpointsVisible ? "element" : "none");
    });
  });
}

// ---------- Sidebar ----------
function renderSidebarEmpty(sidebar: HTMLElement): void {
  sidebar.innerHTML = `<div style="padding:16px;font-size:13px;color:#6b7280">
    Click a node to see details. Drag to pan; scroll to zoom.</div>`;
}
function renderSidebar(sidebar: HTMLElement, n: NodeSingular): void {
  const type = n.data("type") as NodeType;
  const id = n.id();
  const label = (n.data("label") as string) || id;
  const snap = snapshotRef;
  let body = "";
  if (snap && type === "tool") {
    const t = snap.nodes.tools?.[id];
    if (t) {
      const starsLine = typeof t.stars === "number"
        ? `<div><strong>GitHub stars:</strong> ★ ${t.stars.toLocaleString("en-US")}${t.stars_updated_at ? ` <span style="color:#9ca3af">(as of ${escapeHtml(String(t.stars_updated_at))})</span>` : ""}</div>`
        : "";
      body = `
        <div><strong>Control paradigm:</strong> ${escapeHtml(t.control_paradigm ?? "—")}</div>
        <div><strong>Temporal phase:</strong> ${escapeHtml(t.temporal_phase ?? "—")}</div>
        <div><strong>Autonomy:</strong> ${escapeHtml(t.autonomy_level ?? "—")}</div>
        <div><strong>Addresses:</strong> ${(t.addresses_failure_modes ?? []).map(escapeHtml).join(", ") || "—"}</div>
        ${starsLine}`;
    }
  } else if (snap && type === "failure_mode") {
    const fm = snap.nodes.failure_modes?.[id];
    if (fm) body = `<p>${escapeHtml(fm.description ?? "")}</p>
      <p style="color:#6b7280;font-size:12px">Crosswalks: ${(fm.crosswalks ?? []).length}</p>`;
  } else if (snap && type === "taxonomy") {
    const tx = snap.nodes.taxonomies?.[id];
    if (tx) body = `<p>Owner: ${escapeHtml(tx.owner ?? "—")}</p>
      <p style="color:#6b7280;font-size:12px">${(tx.categories ?? []).length} categories</p>`;
  } else if (snap && type === "paper") {
    const p = snap.nodes.papers?.[id];
    if (p) body = `<p>${escapeHtml(p.title ?? "")}</p>
      <p style="color:#6b7280;font-size:12px">${escapeHtml(formatAuthors(p.authors))}${p.year ? ` (${escapeHtml(String(p.year))})` : ""}</p>`;
  }
  const routeType = type === "tool" ? "tools"
    : type === "failure_mode" ? "failure-modes"
    : type === "taxonomy" ? "taxonomies"
    : "papers";
  sidebar.innerHTML = `
    <div style="padding:16px;font-size:13px;line-height:1.5">
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:#6b7280">${escapeHtml(type.replace("_", " "))}</div>
      <div style="font-size:18px;font-weight:600;margin:2px 0">${escapeHtml(label)}</div>
      <div style="font-size:11px;color:#9ca3af;font-family:ui-monospace,monospace;margin-bottom:10px">${escapeHtml(id)}</div>
      ${body}
      <a style="display:inline-block;margin-top:12px;color:#2563eb" href="/${routeType}/${encodeURIComponent(id)}">View full page →</a>
    </div>`;
}

// ---------- Utils ----------
// Node size for Tool nodes. Log-scaled so a gradient is visible without
// popular tools overwhelming the canvas. Range [18, 36] px.
//   0 stars      → 18   (no signal, tool still visible)
//   100 stars    → ~22
//   1,000 stars  → ~26
//   10,000 stars → ~30
//   72,000 stars → ~34
function toolSizeFromStars(stars: number | null | undefined): number {
  const s = typeof stars === "number" && Number.isFinite(stars) ? Math.max(stars, 0) : 0;
  const raw = 18 + Math.log10(s + 1) * 4;
  return Math.max(18, Math.min(36, raw));
}

function shortPaperLabel(p: Paper): string {
  const a = formatAuthors(p.authors).split(",")[0] || p.id;
  return `${a}${p.year ? ` ${p.year}` : ""}`;
}
function formatAuthors(a: Paper["authors"]): string {
  if (!a) return "";
  return Array.isArray(a) ? a.join(", ") : String(a);
}
function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

// KGGraph.ts — Cytoscape.js-powered knowledge-graph visualization for SAICA-KG.
// Runtime: fetches /api/v1/graph.json (the slice of the graph this page draws; lib/graph-data.ts) and renders into #cy.
import cytoscape from "cytoscape";
import type { Core, ElementDefinition, LayoutOptions, NodeSingular, EventObjectNode, Stylesheet } from "cytoscape";
import { fmUrl, toolUrl } from "../lib/seo";
import { escapeHtml } from "../lib/format";
import type { GraphData, GraphPaper } from "../lib/graph-data";

// ---------- Types ----------
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
let snapshotRef: GraphData | null = null;

export async function mountKGGraph(opts: {
  container: HTMLElement; sidebar: HTMLElement; filters: HTMLElement;
  layoutSelect: HTMLSelectElement; resetBtn: HTMLButtonElement;
  search: HTMLInputElement; focusNodeId?: string | null;
  // Keyboard access (all optional so the mouse-only path keeps working).
  // nodeList: element that receives a plain HTML list of the nodes (screen-reader / keyboard alternative).
  // onActivate: called after a node's details were rendered by keyboard (graph, search Enter, list button);
  //   `returnTo` is where focus should go back to when the details close.
  // isDetailsOpen: lets Escape on the graph close the details card first and clear the selection only after.
  nodeList?: HTMLElement | null;
  onActivate?: (returnTo: HTMLElement) => void;
  isDetailsOpen?: () => boolean;
}): Promise<void> {
  const { container, sidebar, filters, layoutSelect, resetBtn, search, focusNodeId } = opts;

  let snapshot: GraphData;
  try {
    const res = await fetch("/api/v1/graph.json");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    snapshot = (await res.json()) as GraphData;
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
    if (et === "crosswalks") style.label = "data(label)";
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
      // Keyboard focus ring (navy, same colour as the site's :focus-visible outline). Last so it wins over
      // kg-dim; its width is re-applied per zoom level in paintRing() so it stays ~3 px on screen.
      {
        selector: "node.kg-kbfocus",
        style: {
          "outline-color": "#1f3a93", "outline-opacity": 1, "outline-style": "solid",
          "outline-width": 3, "outline-offset": 3,
          opacity: 1, "text-opacity": 1, "z-index": 999,
          color: "#1f3a93", "font-weight": 700,
        },
      },
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
        const aliases = (n.data("aliases") as string[] | undefined) ?? [];
        const hay = [n.data("label") || "", n.id(), ...aliases].join(" ").toLowerCase();
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

  const selectNode = (n: NodeSingular) => {
    cy!.nodes().unselect();
    n.select();
    clickFocusId = n.id();
    applyFocus();
    renderSidebar(sidebar, n);
  };
  const clearSelection = () => {
    cy!.nodes().unselect();
    clickFocusId = null;
    applyFocus();
    renderSidebarEmpty(sidebar);
  };

  const kb = setupKeyboard({
    cy, container, search, nodeList: opts.nodeList ?? null,
    selectNode, clearSelection,
    hasSelection: () => clickFocusId !== null,
    onActivate: opts.onActivate, isDetailsOpen: opts.isDetailsOpen,
  });

  cy.on("tap", "node", (evt: EventObjectNode) => {
    selectNode(evt.target);
    kb.syncFromPointer(evt.target);
  });
  cy.on("tap", (evt) => {
    if (evt.target === cy) clearSelection();
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
    kb.filtersChanged();
  });
  filters.addEventListener("change", () => { applyFilters(filters, search.value); applyFocus(); kb.filtersChanged(); });
  search.addEventListener("input", () => { applyFilters(filters, search.value); applyFocus(); });

  // Apply the filter boxes as they stand at load (Papers and the two paper edge types start unticked), so the
  // canvas, the node list and the keyboard order agree from the first paint. A node asked for with ?node= is
  // made visible first.
  if (focusNodeId) {
    const type = cy.getElementById(focusNodeId).data("type") as string | undefined;
    const box = type ? filters.querySelector<HTMLInputElement>(`input[name="type-${type}"]`) : null;
    if (box && !box.checked) box.checked = true;
  }
  applyFilters(filters, search.value);
  kb.filtersChanged();

  if (focusNodeId) {
    const n = cy.getElementById(focusNodeId);
    if (n && n.nonempty()) {
      cy.one("layoutstop", () => {
        cy!.animate({ center: { eles: n }, zoom: 1.4 }, { duration: 400 });
        n.select();
        clickFocusId = n.id();
        applyFocus();
        renderSidebar(sidebar, n as NodeSingular);
        kb.syncFromPointer(n as NodeSingular);
      });
    }
  }

  renderSidebarEmpty(sidebar);
}

// ---------- Keyboard + screen-reader access ----------
// Cytoscape draws on a <canvas>, so nodes are not DOM elements. The container becomes one Tab stop
// (role=application); a "current" node is tracked here and drawn with a navy outline ring. Arrow keys move
// to the nearest visible node in that direction, Enter/Space opens the same details card a click opens,
// Escape closes it (graph.astro) or clears the selection. Changes are announced in a polite live region.
// A plain list of links (opts.nodeList) and Enter-in-search give non-spatial routes to every node.
const TYPE_LABEL: Record<NodeType, string> = {
  tool: "tool", failure_mode: "failure mode", taxonomy: "taxonomy", paper: "paper",
};
const TYPE_PLURAL: Record<NodeType, string> = {
  failure_mode: "Failure modes", tool: "Tools", taxonomy: "Taxonomies", paper: "Papers",
};
const SR_ONLY = "position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;"
  + "clip:rect(0,0,0,0);white-space:nowrap;border:0";

function pageUrlFor(type: NodeType, id: string): string {
  // Canonical page URLs (hyphenated failure-mode slugs, trailing slash); see lib/seo.ts.
  return type === "tool" ? toolUrl(encodeURIComponent(id))
    : type === "failure_mode" ? fmUrl(encodeURIComponent(id))
    : type === "taxonomy" ? `/taxonomies/${encodeURIComponent(id)}/`
    : `/papers/${encodeURIComponent(id)}/`;
}

function setupKeyboard(o: {
  cy: Core; container: HTMLElement; search: HTMLInputElement; nodeList: HTMLElement | null;
  selectNode: (n: NodeSingular) => void; clearSelection: () => void; hasSelection: () => boolean;
  onActivate?: (returnTo: HTMLElement) => void; isDetailsOpen?: () => boolean;
}): { syncFromPointer: (n: NodeSingular) => void; filtersChanged: () => void } {
  const { cy, container, search, nodeList } = o;
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

  // --- ARIA scaffolding (created here so both page shells in graph.astro get it) ---
  const help = document.createElement("p");
  help.id = "kg-kbd-help";
  help.style.cssText = SR_ONLY;
  help.textContent = "Interactive graph. Use the arrow keys to move between nodes; Home and End jump to the "
    + "first and last node. Press Enter or Space to open the focused node's details, and Escape to close them. "
    + "Plus and minus zoom, 0 fits the whole graph. The search box above jumps to a node by name, and a plain "
    + "list of all nodes follows the graph.";
  const live = document.createElement("div");
  live.id = "kg-kbd-live";
  live.setAttribute("role", "status");
  live.setAttribute("aria-live", "polite");
  live.setAttribute("aria-atomic", "true");
  live.style.cssText = SR_ONLY;
  container.after(help, live);

  container.tabIndex = 0;
  container.setAttribute("role", "application");
  container.setAttribute("aria-label", "Knowledge graph");
  container.setAttribute("aria-describedby", help.id);

  // Search: datalist suggestions + a hint; Enter jumps to the best match.
  const datalist = document.createElement("datalist");
  datalist.id = "kg-search-options";
  search.after(datalist);
  search.setAttribute("list", datalist.id);
  const searchHint = document.createElement("span");
  searchHint.id = "kg-search-hint";
  searchHint.style.cssText = SR_ONLY;
  searchHint.textContent = "Matching nodes are highlighted as you type. Press Enter to open the best match.";
  search.after(searchHint);
  search.setAttribute("aria-describedby", searchHint.id);

  let announceTimer: number | undefined;
  const announce = (msg: string) => {
    // Clear then set, so repeating the same text is still announced.
    live.textContent = "";
    clearTimeout(announceTimer);
    announceTimer = window.setTimeout(() => { live.textContent = msg; }, 40);
  };

  // --- Input modality: show the ring only for keyboard users ---
  let keyboardMode = false;
  document.addEventListener("keydown", () => { keyboardMode = true; }, true);
  document.addEventListener("pointerdown", () => { keyboardMode = false; }, true);

  let currentId: string | null = null;
  let ringed: NodeSingular | null = null;

  const visibleNodes = () => cy.nodes(":visible");
  const current = (): NodeSingular | null => {
    if (!currentId) return null;
    const n = cy.getElementById(currentId);
    return n.nonempty() && n.visible() ? (n as NodeSingular) : null;
  };
  const readingOrder = () => visibleNodes().toArray()
    .map((n) => n as NodeSingular)
    .sort((a, b) => (a.position("y") - b.position("y")) || (a.position("x") - b.position("x")));

  const paintRing = () => {
    if (!ringed) return;
    // Model units scale with zoom; divide so the ring stays about 3 px on screen.
    const z = cy.zoom() || 1;
    ringed.style({ "outline-width": 3 / z, "outline-offset": 3 / z });
  };
  const unring = () => {
    if (!ringed) return;
    ringed.removeClass("kg-kbfocus");
    ringed.removeStyle("outline-width outline-offset");
    ringed = null;
  };
  const ring = (n: NodeSingular | null) => {
    if (ringed && n && ringed.same(n)) { paintRing(); return; }
    unring();
    if (!n) return;
    ringed = n;
    n.addClass("kg-kbfocus");
    paintRing();
  };
  cy.on("zoom", paintRing);

  const describe = (n: NodeSingular): string => {
    const type = n.data("type") as NodeType;
    const deg = n.connectedEdges(":visible").length;
    return `${n.data("label") || n.id()}, ${TYPE_LABEL[type] ?? type}. `
      + `${deg} connection${deg === 1 ? "" : "s"}.${n.selected() ? " Selected." : ""}`;
  };

  const ensureInView = (n: NodeSingular, forceCenter = false) => {
    const bb = n.renderedBoundingBox({ includeLabels: true });
    const w = cy.width(), h = cy.height(), m = 24;
    const outside = bb.x1 < m || bb.y1 < m || bb.x2 > w - m || bb.y2 > h - m;
    if (!outside && !forceCenter) return;
    if (reduceMotion) cy.center(n);
    else cy.animate({ center: { eles: n } }, { duration: 200 });
  };

  const moveTo = (n: NodeSingular | null, opts: { announce?: boolean; center?: boolean } = {}) => {
    if (!n) return;
    currentId = n.id();
    ring(document.activeElement === container ? n : null);
    ensureInView(n, !!opts.center);
    if (opts.announce !== false) announce(describe(n));
  };

  const nearestToViewportCenter = (): NodeSingular | null => {
    const e = cy.extent();
    const cx = (e.x1 + e.x2) / 2, cyy = (e.y1 + e.y2) / 2;
    let best: NodeSingular | null = null, bestD = Infinity;
    visibleNodes().forEach((n) => {
      const p = n.position();
      const d = (p.x - cx) ** 2 + (p.y - cyy) ** 2;
      if (d < bestD) { bestD = d; best = n as NodeSingular; }
    });
    return best;
  };

  const startNode = (): NodeSingular | null => {
    const c = current();
    if (c) return c;
    const sel = cy.nodes(":selected:visible");
    if (sel.nonempty()) return sel[0] as NodeSingular;
    return nearestToViewportCenter();
  };

  // Nearest visible node in a direction: candidates inside a ~70 degree cone score by distance along the axis
  // plus twice the sideways offset; if the cone is empty, anything in that half-plane qualifies.
  const nearestInDirection = (from: NodeSingular, dx: number, dy: number): NodeSingular | null => {
    const p0 = from.position();
    let best: NodeSingular | null = null, bestScore = Infinity;
    visibleNodes().forEach((n) => {
      if (n.same(from)) return;
      const p = n.position();
      const vx = p.x - p0.x, vy = p.y - p0.y;
      const along = vx * dx + vy * dy;
      if (along <= 0.5) return;
      const perp = Math.abs(vx * dy - vy * dx);
      const score = along + 2 * perp + (perp > along * 1.4 ? 1e7 : 0);
      if (score < bestScore) { bestScore = score; best = n as NodeSingular; }
    });
    return best;
  };

  const activate = (n: NodeSingular, returnTo: HTMLElement) => {
    o.selectNode(n);
    currentId = n.id();
    announce(`${describe(n)} Details open.`);
    o.onActivate?.(returnTo);
  };

  container.addEventListener("focus", () => {
    if (!keyboardMode) return;
    const n = startNode();
    if (!n) { announce("No nodes are shown. Change the filters to show some."); return; }
    moveTo(n);
  });
  container.addEventListener("blur", () => ring(null));

  container.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    keyboardMode = true;
    const dirs: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
    };
    const cur = startNode();
    if (e.key in dirs) {
      e.preventDefault();
      if (!cur) return;
      if (!current()) { moveTo(cur); return; }
      const [dx, dy] = dirs[e.key];
      const next = nearestInDirection(cur, dx, dy);
      if (next) moveTo(next);
      else announce(`No node further ${e.key.replace("Arrow", "").toLowerCase()}. ${describe(cur)}`);
      return;
    }
    switch (e.key) {
      case "Home":
      case "End": {
        e.preventDefault();
        const order = readingOrder();
        moveTo(e.key === "Home" ? order[0] ?? null : order[order.length - 1] ?? null);
        return;
      }
      case "Enter":
      case " ":
        e.preventDefault();
        if (cur) { moveTo(cur, { announce: false }); activate(cur, container); }
        return;
      case "Escape":
        // An open details card is closed by graph.astro's document-level handler first.
        if (o.isDetailsOpen?.()) return;
        if (o.hasSelection()) {
          o.clearSelection();
          announce("Selection cleared.");
        }
        return;
      case "+":
      case "=":
      case "-":
      case "_": {
        e.preventDefault();
        const factor = e.key === "+" || e.key === "=" ? 1.25 : 0.8;
        const c = current();
        const pos = c ? c.renderedPosition() : { x: cy.width() / 2, y: cy.height() / 2 };
        cy.zoom({ level: cy.zoom() * factor, renderedPosition: pos });
        announce(`Zoom ${Math.round(cy.zoom() * 100)} percent.`);
        return;
      }
      case "0":
        e.preventDefault();
        cy.fit(undefined, 30);
        announce("Whole graph in view.");
        return;
    }
  });

  // Search: Enter jumps to the best visible match (exact > prefix > word prefix > substring; shorter first).
  const bestMatch = (raw: string): NodeSingular | null => {
    const q = raw.trim().toLowerCase();
    if (!q) return null;
    let best: NodeSingular | null = null, bestRank = Infinity, bestLen = Infinity;
    visibleNodes().forEach((n) => {
      const label = String(n.data("label") || "").toLowerCase();
      const id = n.id().toLowerCase();
      const aliases = ((n.data("aliases") as string[] | undefined) ?? []).map((a) => a.toLowerCase());
      let rank = Infinity;
      if (label === q || id === q || aliases.includes(q)) rank = 0;
      else if (label.startsWith(q) || id.startsWith(q)) rank = 1;
      else if (label.split(/[\s\-_/(]+/).some((w) => w.startsWith(q))) rank = 2;
      else if ([label, id, ...aliases].some((s) => s.includes(q))) rank = 3;
      if (rank < bestRank || (rank === bestRank && rank < Infinity && label.length < bestLen)) {
        best = n as NodeSingular; bestRank = rank; bestLen = label.length;
      }
    });
    return best;
  };
  search.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const n = bestMatch(search.value);
    if (!n) { announce(search.value.trim() ? `No shown node matches "${search.value.trim()}".` : "Type a node name first."); return; }
    moveTo(n, { announce: false, center: true });
    activate(n, container);
  });

  // --- Plain list alternative ---
  const listItems = new Map<string, HTMLLIElement>();
  const groups: { type: NodeType; section: HTMLElement }[] = [];
  let listCount: HTMLElement | null = null;
  if (nodeList) {
    nodeList.innerHTML = "";
    listCount = document.createElement("p");
    listCount.className = "kg-list-count";
    nodeList.appendChild(listCount);
    for (const type of ["failure_mode", "tool", "taxonomy", "paper"] as NodeType[]) {
      const nodes = cy.nodes(`[type = "${type}"]`).toArray().map((n) => n as NodeSingular)
        .sort((a, b) => String(a.data("label")).localeCompare(String(b.data("label"))));
      if (nodes.length === 0) continue;
      const section = document.createElement("section");
      const h = document.createElement("h2");
      h.textContent = TYPE_PLURAL[type];
      const ul = document.createElement("ul");
      for (const n of nodes) {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = pageUrlFor(type, n.id());
        a.textContent = String(n.data("label") || n.id());
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = "Show in graph";
        btn.setAttribute("aria-label", `Show ${a.textContent} in the graph`);
        btn.addEventListener("click", () => {
          const node = cy.getElementById(n.id());
          if (node.empty() || !node.visible()) return;
          moveTo(node as NodeSingular, { announce: false, center: true });
          activate(node as NodeSingular, btn);
        });
        li.append(a, " ", btn);
        ul.appendChild(li);
        listItems.set(n.id(), li);
      }
      section.append(h, ul);
      nodeList.appendChild(section);
      groups.push({ type, section });
    }
  }

  const refreshDerived = () => {
    const vis = new Set(visibleNodes().map((n) => n.id()));
    for (const [id, li] of listItems) li.hidden = !vis.has(id);
    for (const g of groups) g.section.hidden = !Array.from(g.section.querySelectorAll("li")).some((li) => !li.hidden);
    if (listCount) listCount.textContent = `${vis.size} node${vis.size === 1 ? "" : "s"} shown with the current filters.`;
    // Datalist: one option per distinct visible label.
    const labels = new Set<string>();
    visibleNodes().forEach((n) => { labels.add(String(n.data("label") || n.id())); });
    datalist.replaceChildren(...Array.from(labels).sort().map((l) => {
      const opt = document.createElement("option");
      opt.value = l;
      return opt;
    }));
  };
  refreshDerived();

  return {
    syncFromPointer: (n) => { currentId = n.id(); ring(null); },
    filtersChanged: () => {
      if (currentId && !current()) {
        currentId = null;
        ring(null);
      }
      refreshDerived();
    },
  };
}

// ---------- Element construction ----------
function buildElements(s: GraphData): { elements: ElementDefinition[]; nodeCount: number } {
  const elements: ElementDefinition[] = [];
  const tools = s.nodes.tools ?? {};
  const fms = s.nodes.failure_modes ?? {};
  const taxos = s.nodes.taxonomies ?? {};
  // graph.json carries only the papers a tool or a failure mode points to, so every one of them is drawn.
  const papers = s.nodes.papers ?? {};

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
  for (const fm of Object.values(fms)) elements.push({ data: {
    id: fm.id, type: "failure_mode", label: fm.name || fm.id,
    aliases: fm.aliases ?? [],
  }});
  for (const tx of Object.values(taxos)) elements.push({ data: { id: tx.id, type: "taxonomy", label: tx.name || tx.id } });
  for (const p of Object.values(papers)) elements.push({ data: { id: p.id, type: "paper", label: shortPaperLabel(p) } });

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
    for (const pid of fm.prior_work ?? []) if (papers[pid]) addEdge(fm.id, pid, "prior_work");
  }
  // One link per (failure mode, taxonomy) pair, labelled with its strongest mapping and how many more there are.
  for (const cw of s.crosswalks ?? []) {
    if (!fms[cw.failure_mode] || !taxos[cw.taxonomy]) continue;
    addEdge(cw.failure_mode, cw.taxonomy, "crosswalks", {
      confidence: cw.confidence, mappings: cw.mappings,
      label: cw.mappings > 1 ? `${cw.confidence} +${cw.mappings - 1}` : cw.confidence,
    });
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
      <p style="color:#6b7280;font-size:12px">${escapeHtml(crosswalkSummary(snap, id))}</p>`;
  } else if (snap && type === "taxonomy") {
    const tx = snap.nodes.taxonomies?.[id];
    if (tx) body = `<p>Owner: ${escapeHtml(tx.owner ?? "—")}</p>
      <p style="color:#6b7280;font-size:12px">${tx.categories ?? 0} categories</p>`;
  } else if (snap && type === "paper") {
    const p = snap.nodes.papers?.[id];
    if (p) body = `<p>${escapeHtml(p.title ?? "")}</p>
      <p style="color:#6b7280;font-size:12px">${escapeHtml(formatAuthors(p.authors))}${p.year ? ` (${escapeHtml(String(p.year))})` : ""}</p>`;
  }
  const pageUrl = pageUrlFor(type, id);
  // The title is a focus target (tabindex=-1) for keyboard activation; see onActivate in graph.astro.
  sidebar.innerHTML = `
    <div style="padding:16px;font-size:13px;line-height:1.5">
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:#6b7280">${escapeHtml(type.replace("_", " "))}</div>
      <div id="kg-detail-title" role="heading" aria-level="2" tabindex="-1" style="font-size:18px;font-weight:600;margin:2px 0">${escapeHtml(label)}</div>
      <div style="font-size:11px;color:#9ca3af;font-family:ui-monospace,monospace;margin-bottom:10px">${escapeHtml(id)}</div>
      ${body}
      <a style="display:inline-block;margin-top:12px;color:#2563eb" href="${pageUrl}">View full page →</a>
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

// "Crosswalks: 9 mappings in 5 taxonomies (strongest: 2 exact, 3 partial)" for a failure mode's details card.
function crosswalkSummary(s: GraphData, fmId: string): string {
  const pairs = (s.crosswalks ?? []).filter((c) => c.failure_mode === fmId);
  if (pairs.length === 0) return "Crosswalks: none";
  const total = pairs.reduce((n, c) => n + c.mappings, 0);
  const strongest: Record<string, number> = {};
  for (const c of pairs) strongest[c.confidence] = (strongest[c.confidence] ?? 0) + 1;
  const parts = Object.entries(strongest).map(([conf, n]) => `${n} ${conf}`);
  return `Crosswalks: ${total} mapping${total === 1 ? "" : "s"} in ${pairs.length} `
    + `taxonom${pairs.length === 1 ? "y" : "ies"} (strongest per taxonomy: ${parts.join(", ")})`;
}

function shortPaperLabel(p: GraphPaper): string {
  const a = formatAuthors(p.authors).split(",")[0] || p.id;
  return `${a}${p.year ? ` ${p.year}` : ""}`;
}
function formatAuthors(a: GraphPaper["authors"] | string | undefined): string {
  if (!a) return "";
  return Array.isArray(a) ? a.join(", ") : String(a);
}

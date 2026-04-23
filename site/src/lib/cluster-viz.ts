// Small helpers for the /taxonomy-study visualizations. All geometry is pure
// and frame-agnostic: callers are responsible for mapping raw coords to SVG
// viewport space. Dependency-free.

const SVG_NS = "http://www.w3.org/2000/svg";

export interface V2 {
  x: number;
  y: number;
}

// Tiny SVG element factory to keep caller render code terse.
export function mkSvg<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | number>,
  text?: string,
): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG_NS, tag);
  for (const k in attrs) node.setAttribute(k, String(attrs[k]));
  if (text !== undefined) node.textContent = text;
  return node;
}

// Render a shaded hull (polygon or fallback circle) and a centered label for
// one cluster. Returns the SVG children to append. Kept here so the page
// render loop is a few lines.
export function renderClusterRegion(
  projected: V2[],
  color: string,
  label: string,
  opts: { fontSize?: number; labelMaxLen?: number } = {},
): SVGElement[] {
  const hullAttrs = { fill: color, "fill-opacity": "0.18", stroke: color, "stroke-width": "0.35" };
  const out: SVGElement[] = [];
  let anchor: V2;
  if (projected.length < 3) {
    const c = meanPoint(projected);
    let r = 0;
    for (const p of projected) r = Math.max(r, Math.hypot(p.x - c.x, p.y - c.y));
    r = Math.max(r + 1.8, 2.2);
    out.push(mkSvg("circle", { cx: c.x.toFixed(3), cy: c.y.toFixed(3), r: r.toFixed(3), ...hullAttrs }));
    anchor = c;
  } else {
    const hull = padHull(convexHull(projected), 1.2);
    out.push(mkSvg("polygon", {
      points: hull.map((p) => `${p.x.toFixed(3)},${p.y.toFixed(3)}`).join(" "),
      "stroke-linejoin": "round", ...hullAttrs,
    }));
    anchor = meanPoint(hull);
  }
  const maxLen = opts.labelMaxLen ?? 22;
  const text = label.length > maxLen ? label.slice(0, maxLen - 1) + "…" : label;
  out.push(mkSvg("text", {
    x: anchor.x.toFixed(3), y: anchor.y.toFixed(3), "text-anchor": "middle",
    "font-family": "ui-sans-serif, system-ui, sans-serif",
    "font-size": String(opts.fontSize ?? 2.1),
    "font-weight": "600", stroke: "white", "stroke-width": "0.7",
    "stroke-linejoin": "round", "paint-order": "stroke fill",
    fill: color, "pointer-events": "none",
  }, text));
  return out;
}

// Andrew's monotone-chain convex hull. Returns points in CCW order (or CW
// depending on coordinate system; we do not care for rendering). Duplicates
// and collinear points are tolerated. Returns the input unchanged for n < 3.
export function convexHull(points: V2[]): V2[] {
  if (points.length < 3) return points.slice();
  const pts = points
    .slice()
    .sort((a, b) => (a.x === b.x ? a.y - b.y : a.x - b.x));
  const cross = (o: V2, a: V2, b: V2): number =>
    (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower: V2[] = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) {
      lower.pop();
    }
    lower.push(p);
  }
  const upper: V2[] = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) {
      upper.pop();
    }
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

// Centroid of an arbitrary point set (arithmetic mean, good enough for
// placing a label on top of a cluster region).
export function meanPoint(points: V2[]): V2 {
  if (points.length === 0) return { x: 0, y: 0 };
  let sx = 0;
  let sy = 0;
  for (const p of points) {
    sx += p.x;
    sy += p.y;
  }
  return { x: sx / points.length, y: sy / points.length };
}

// Expand a convex polygon outward from its centroid by `padding` (same units
// as the points). Gives the hull a bit of breathing room around the dots it
// encloses so the stroke does not clip them.
export function padHull(hull: V2[], padding: number): V2[] {
  if (hull.length === 0) return hull;
  const c = meanPoint(hull);
  return hull.map((p) => {
    const dx = p.x - c.x;
    const dy = p.y - c.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    return { x: p.x + (dx / len) * padding, y: p.y + (dy / len) * padding };
  });
}

// Sankey layout across N vertical columns. Each column gets a stack of bars
// and ribbons connect adjacent columns. Caller decides counting semantics by
// providing, for each column, a grouping key per item.
export interface SankeyColumnSpec<T> {
  id: string;
  label: string;
  key: (item: T) => string;
  // Optional per-bar display name; defaults to the group key.
  barName?: (key: string) => string;
  // Optional per-bar color; defaults come from a palette in the caller.
  barColor?: (key: string) => string | undefined;
}

export interface SankeyBar {
  col: number;
  key: string;
  name: string;
  size: number;
  y0: number; // top, in layout units (0..height)
  y1: number; // bottom
  color: string;
}

export interface SankeyRibbon {
  from: SankeyBar;
  to: SankeyBar;
  size: number;
  // Sub-band positions inside each endpoint bar (for stacking ribbons inside
  // a bar so a tall bar with 3 outgoing ribbons renders as 3 sub-slices).
  fromY0: number;
  fromY1: number;
  toY0: number;
  toY1: number;
  color: string;
}

export interface SankeyLayout {
  bars: SankeyBar[];
  ribbons: SankeyRibbon[];
  columnX: number[]; // x of each column's bar (left edge)
  barWidth: number;
  width: number;
  height: number;
}

export interface SankeyOptions<T> {
  items: T[];
  columns: SankeyColumnSpec<T>[];
  width: number;
  height: number;
  barWidth?: number; // default 16
  barGap?: number; // default 4 (vertical gap between bars in a column)
  palette: string[]; // fallback palette for bars with no explicit color
}

export function layoutSankey<T>(opts: SankeyOptions<T>): SankeyLayout {
  const barWidth = opts.barWidth ?? 16;
  const barGap = opts.barGap ?? 4;
  const nCols = opts.columns.length;
  const colSpacing = (opts.width - barWidth) / Math.max(1, nCols - 1);
  const columnX: number[] = [];
  for (let i = 0; i < nCols; i++) columnX.push(i * colSpacing);

  // Build bars per column, sorted by size desc so tall bars anchor the top.
  const columnBars: SankeyBar[][] = [];
  for (let c = 0; c < nCols; c++) {
    const spec = opts.columns[c];
    const counts = new Map<string, number>();
    for (const item of opts.items) {
      const k = spec.key(item);
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    const entries = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
    const totalBars = entries.length;
    const totalGap = Math.max(0, totalBars - 1) * barGap;
    const availH = opts.height - totalGap;
    const total = opts.items.length || 1;
    let y = 0;
    const bars: SankeyBar[] = [];
    for (let i = 0; i < entries.length; i++) {
      const [k, size] = entries[i];
      const h = Math.max(2, (size / total) * availH);
      const name = spec.barName ? spec.barName(k) : k;
      const color = spec.barColor?.(k) ?? opts.palette[i % opts.palette.length];
      bars.push({ col: c, key: k, name, size, y0: y, y1: y + h, color });
      y += h + barGap;
    }
    columnBars.push(bars);
  }

  // Build ribbons between every adjacent column pair. For each bar we track a
  // running cursor on each side so sub-bands stack cleanly.
  const leftCursor = new Map<string, number>(); // barId -> cumulative px
  const rightCursor = new Map<string, number>();
  const ribbons: SankeyRibbon[] = [];
  const barId = (b: SankeyBar): string => `${b.col}::${b.key}`;

  for (let c = 0; c < nCols - 1; c++) {
    const left = columnBars[c];
    const right = columnBars[c + 1];
    const lByKey = new Map(left.map((b) => [b.key, b]));
    const rByKey = new Map(right.map((b) => [b.key, b]));
    // Count pairs (leftKey, rightKey).
    const pairs = new Map<string, number>();
    for (const item of opts.items) {
      const lk = opts.columns[c].key(item);
      const rk = opts.columns[c + 1].key(item);
      const kk = `${lk}${rk}`;
      pairs.set(kk, (pairs.get(kk) ?? 0) + 1);
    }
    // For ribbon ordering inside a bar, process groups anchored on left bars
    // (top-to-bottom), then for each left bar, its outgoing ribbons are sorted
    // by destination bar's y0 so they do not cross unnecessarily.
    const sortedLeft = left.slice(); // already sorted by size desc (top-down)
    for (const lb of sortedLeft) {
      const outgoing: Array<{ rb: SankeyBar; size: number }> = [];
      for (const rb of right) {
        const s = pairs.get(`${lb.key}${rb.key}`) ?? 0;
        if (s > 0) outgoing.push({ rb, size: s });
      }
      outgoing.sort((a, b) => a.rb.y0 - b.rb.y0);
      for (const { rb, size } of outgoing) {
        const lbH = lb.y1 - lb.y0;
        const rbH = rb.y1 - rb.y0;
        const lStart = leftCursor.get(barId(lb)) ?? 0;
        const rStart = rightCursor.get(barId(rb)) ?? 0;
        const lShare = (size / lb.size) * lbH;
        const rShare = (size / rb.size) * rbH;
        const fromY0 = lb.y0 + lStart;
        const fromY1 = fromY0 + lShare;
        const toY0 = rb.y0 + rStart;
        const toY1 = toY0 + rShare;
        leftCursor.set(barId(lb), lStart + lShare);
        rightCursor.set(barId(rb), rStart + rShare);
        ribbons.push({
          from: lb,
          to: rb,
          size,
          fromY0,
          fromY1,
          toY0,
          toY1,
          color: lb.color,
        });
        void rByKey; void lByKey; // lint
      }
    }
  }

  const bars = columnBars.flat();
  return { bars, ribbons, columnX, barWidth, width: opts.width, height: opts.height };
}

// Build the SVG path `d` for one Sankey ribbon. Two cubic beziers sharing a
// vertical midline — the canonical Sankey shape.
export function ribbonPath(r: SankeyRibbon, columnX: number[], barWidth: number): string {
  const x0 = columnX[r.from.col] + barWidth;
  const x1 = columnX[r.to.col];
  const midX = (x0 + x1) / 2;
  return [
    `M ${x0} ${r.fromY0}`,
    `C ${midX} ${r.fromY0}, ${midX} ${r.toY0}, ${x1} ${r.toY0}`,
    `L ${x1} ${r.toY1}`,
    `C ${midX} ${r.toY1}, ${midX} ${r.fromY1}, ${x0} ${r.fromY1}`,
    `Z`,
  ].join(" ");
}

// High-level Sankey renderer. Mounts the diagram into `root`, wires hover
// behavior, and returns the ribbon paths so the caller can reset state.
export interface SankeyRenderOpts {
  root: SVGSVGElement;
  layout: SankeyLayout;
  marginX: number;
  marginY: number;
  columnTitles: string[];
  onHover?: (ribbon: SankeyRibbon, ev: MouseEvent) => void;
  onLeave?: () => void;
}
const SANS = "ui-sans-serif, system-ui, sans-serif";

export function renderSankeyInto(opts: SankeyRenderOpts): SVGPathElement[] {
  const { root, layout, marginX, marginY } = opts;
  while (root.firstChild) root.removeChild(root.firstChild);

  for (let c = 0; c < opts.columnTitles.length; c++) {
    root.appendChild(mkSvg("text", {
      x: marginX + layout.columnX[c] + layout.barWidth / 2, y: marginY + 14,
      "text-anchor": "middle", "font-family": SANS, "font-size": "12",
      "font-weight": "600", fill: "#334155",
    }, opts.columnTitles[c]));
  }

  const translate = `translate(${marginX}, ${marginY + 28})`;
  const gRibbons = mkSvg("g", { transform: translate });
  const gBars = mkSvg("g", { transform: translate });
  root.appendChild(gRibbons);
  root.appendChild(gBars);

  const ribbonEls: SVGPathElement[] = [];
  for (const r of layout.ribbons) {
    const path = mkSvg("path", {
      d: ribbonPath(r, layout.columnX, layout.barWidth),
      fill: r.color, "fill-opacity": "0.32", stroke: "none",
    });
    path.style.cursor = "pointer";
    path.dataset.fromBar = `${r.from.col}::${r.from.key}`;
    path.dataset.toBar = `${r.to.col}::${r.to.key}`;
    path.dataset.size = String(r.size);
    if (opts.onHover) path.addEventListener("mouseenter", (ev) => opts.onHover!(r, ev as MouseEvent));
    if (opts.onLeave) path.addEventListener("mouseleave", () => opts.onLeave!());
    gRibbons.appendChild(path);
    ribbonEls.push(path);
  }

  for (const b of layout.bars) {
    const rect = mkSvg("rect", {
      x: layout.columnX[b.col], y: b.y0,
      width: layout.barWidth, height: Math.max(1, b.y1 - b.y0),
      fill: b.color, "fill-opacity": "0.9",
      stroke: "white", "stroke-width": "1",
    });
    rect.style.cursor = "pointer";
    rect.dataset.barId = `${b.col}::${b.key}`;
    rect.addEventListener("mouseenter", () => {
      const id = `${b.col}::${b.key}`;
      for (const rb of ribbonEls) {
        const hit = rb.dataset.fromBar === id || rb.dataset.toBar === id;
        rb.setAttribute("fill-opacity", hit ? "0.7" : "0.08");
      }
    });
    rect.addEventListener("mouseleave", () => opts.onLeave?.());
    gBars.appendChild(rect);

    const labelX = b.col === 0 ? layout.columnX[b.col] - 6
      : layout.columnX[b.col] + layout.barWidth + 6;
    const nm = b.name.length > 26 ? b.name.slice(0, 25) + "…" : b.name;
    const tx = mkSvg("text", {
      x: labelX, y: (b.y0 + b.y1) / 2 + 3.5,
      "text-anchor": b.col === 0 ? "end" : "start",
      "font-family": SANS, "font-size": "10", fill: "#334155",
      ...(b.y1 - b.y0 < 9 ? { opacity: "0" } : {}),
    }, `${nm} · ${b.size}`);
    gBars.appendChild(tx);
  }
  return ribbonEls;
}

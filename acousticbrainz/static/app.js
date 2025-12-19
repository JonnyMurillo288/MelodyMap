const container = document.getElementById("graph");
const searchInput = document.getElementById("searchInput");
const autocomplete = document.getElementById("autocomplete");
const sidepanel = document.getElementById("sidepanel");

const graph = new graphology.Graph();
let renderer;

let originalNode = new Map();
let originalEdge = new Map();
let artistIndex = [];
let lockedNode = null;

// =====================================================
// LOAD GRAPH
// =====================================================
fetch("graph.json")
  .then(r => r.json())
  .then(data => {

    // -----------------------------
    // Normalize + spread coordinates
    // -----------------------------
    const xs = data.nodes.map(n => n.attributes.x);
    const ys = data.nodes.map(n => n.attributes.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);

    const SPREAD = 1.4;

    data.nodes.forEach(n => {
      const nx = (n.attributes.x - minX) / (maxX - minX);
      const ny = (n.attributes.y - minY) / (maxY - minY);
      const baseColor = clusterColor(n.attributes.cluster);

      graph.addNode(n.key, {
        label: n.attributes.label,
        x: SPREAD * (0.1 + 0.8 * nx),
        y: SPREAD * (0.1 + 0.8 * ny),
        size: 4,
        color: baseColor,
        baseColor: baseColor,
        cluster: n.attributes.cluster,
        labelColor: "#ffffff",
        zIndex: 0
      });

      artistIndex.push({ key: n.key, label: n.attributes.label });
    });

    data.edges.forEach(e => {
      if (graph.hasNode(e.source) && graph.hasNode(e.target)) {
        graph.addEdge(e.source, e.target, {
          color: "rgba(148,163,184,0.35)",
          size: 1,
          zIndex: 0
        });
      }
    });

    // Cache originals for reset
    graph.forEachNode((n, a) => originalNode.set(n, { ...a }));
    graph.forEachEdge((e, a) => originalEdge.set(e, { ...a }));

    // -----------------------------
    // Sigma
    // -----------------------------
    renderer = new Sigma(graph, container, {
      minCameraRatio: 0.05,
      maxCameraRatio: 10
    });

    // Click = lock
    renderer.on("clickNode", ({ node }) => {
      lockedNode = node;
      highlight(node);
    });

    // Hover = preview
    renderer.on("enterNode", ({ node }) => {
      if (!lockedNode) highlight(node, true);
    });

    renderer.on("leaveNode", () => {
      if (!lockedNode) reset();
    });

    renderer.on("clickStage", reset);

    document.addEventListener("keydown", e => {
      if (e.key === "Escape") reset();
    });
  });

// =====================================================
// HIGHLIGHT LOGIC (PRESERVE CLUSTER COLOR)
// =====================================================
function highlight(nodeKey, preview = false) {
  const neighbors = new Set(graph.neighbors(nodeKey));

  graph.forEachNode(n => {
    const base = graph.getNodeAttribute(n, "baseColor");

    if (n === nodeKey) {
      graph.setNodeAttribute(n, "color", brighten(base, 1.4));
      graph.setNodeAttribute(n, "size", 9);
      graph.setNodeAttribute(n, "labelColor", brighten(base, 1.6));
      graph.setNodeAttribute(n, "zIndex", 3);
    } 
    else if (neighbors.has(n)) {
      graph.setNodeAttribute(n, "color", brighten(base, 1.15));
      graph.setNodeAttribute(n, "size", 6);
      graph.setNodeAttribute(n, "labelColor", "#ffffff");
      graph.setNodeAttribute(n, "zIndex", 2);
    } 
    else {
      graph.setNodeAttribute(n, "color", fade(base, 0.25));
      graph.setNodeAttribute(n, "size", 3);
      graph.setNodeAttribute(n, "labelColor", "rgba(255,255,255,0.35)");
      graph.setNodeAttribute(n, "zIndex", 0);
    }
  });

  graph.forEachEdge((e, a, s, t) => {
    if (s === nodeKey || t === nodeKey) {
      graph.setEdgeAttribute(e, "color", "rgba(255,255,255,0.6)");
      graph.setEdgeAttribute(e, "size", 2);
      graph.setEdgeAttribute(e, "zIndex", 2);
    } else {
      graph.setEdgeAttribute(e, "color", "rgba(148,163,184,0.15)");
      graph.setEdgeAttribute(e, "size", 0.5);
      graph.setEdgeAttribute(e, "zIndex", 0);
    }
  });

  renderer.refresh();
  if (!preview) updateSidepanel(nodeKey);
}

// =====================================================
// RESET
// =====================================================
function reset() {
  lockedNode = null;

  graph.forEachNode(n => graph.mergeNodeAttributes(n, originalNode.get(n)));
  graph.forEachEdge(e => graph.mergeEdgeAttributes(e, originalEdge.get(e)));

  renderer.refresh();
  sidepanel.innerHTML = `<div class="muted">No artist selected</div>`;
}

// =====================================================
// SIDEPANEL
// =====================================================
function updateSidepanel(nodeKey) {
  const label = graph.getNodeAttribute(nodeKey, "label");
  const cluster = graph.getNodeAttribute(nodeKey, "cluster");
  const color = clusterColor(cluster);

  const similar = [];
  graph.forEachNode(n => {
    if (n !== nodeKey && graph.getNodeAttribute(n, "cluster") === cluster) {
      similar.push(graph.getNodeAttribute(n, "label"));
    }
  });

  sidepanel.innerHTML = `
    <div><strong>${label}</strong></div>
    <div class="cluster-chip">
      <span class="cluster-dot" style="background:${color}"></span>
      Cluster ${cluster}
    </div>
    <div class="muted">Similar artists</div>
    ${similar.slice(0, 20).map(a => `<div class="similar">${a}</div>`).join("")}
  `;
}

// =====================================================
// SEARCH + AUTOCOMPLETE
// =====================================================
searchInput.addEventListener("input", () => {
  const q = searchInput.value.toLowerCase();
  autocomplete.innerHTML = "";
  if (!q) return (autocomplete.style.display = "none");

  const matches = artistIndex
    .filter(a => a.label.toLowerCase().includes(q))
    .slice(0, 10);

  matches.forEach(a => {
    const div = document.createElement("div");
    div.className = "autocomplete-item";
    div.textContent = a.label;
    div.onclick = () => {
      lockedNode = a.key;
      highlight(a.key);
      autocomplete.style.display = "none";
    };
    autocomplete.appendChild(div);
  });

  autocomplete.style.display = matches.length ? "block" : "none";
});

document.addEventListener("click", e => {
  if (e.target !== searchInput) autocomplete.style.display = "none";
});

// =====================================================
// COLOR HELPERS
// =====================================================
function clusterColor(c) {
  const colors = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf"
  ];
  return colors[c % colors.length];
}

function brighten(hex, factor) {
  const c = hexToRgb(hex);
  return `rgb(
    ${Math.min(255, c.r * factor)},
    ${Math.min(255, c.g * factor)},
    ${Math.min(255, c.b * factor)}
  )`;
}

function fade(hex, alpha) {
  const c = hexToRgb(hex);
  return `rgba(${c.r}, ${c.g}, ${c.b}, ${alpha})`;
}

function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return {
    r: parseInt(h.substring(0, 2), 16),
    g: parseInt(h.substring(2, 4), 16),
    b: parseInt(h.substring(4, 6), 16)
  };
}

/* ============================================================
   GLOBALS / CONSTANTS
============================================================ */

const Graph = window.graphology.Graph;
const SigmaLib = window.Sigma;

let graph = null;
let renderer = null;

let showNeighbors = true;
const expandedByNode = new Map();

let currentPath = [];
let pathNodeSet = new Set();
let pathEdgeSet = new Set();

let reducerState = {
  hoveredNode: null,
  hoveredNeighbors: new Set(),
};

let clusterSideByNode = new Map();

// auto-expansion timer
let autoExpandInterval = null;

let mobileTapMode = false;
let tappedNode = null; // remembers the currently selected node

// cosmic animation
let cosmicAnimationFrame = null;

// neighbor/autocomplete state
let artistNameList = [];

// colors
const START_COLOR = "#2779bd";
const TARGET_COLOR = "#c53030";
const PATH_NODE_COLOR = "#22c55e";
const NEIGHBOR_NODE_COLOR = "#9ca3af";

const START_SIZE = 35;
const TARGET_SIZE = 35;
const PATH_NODE_SIZE = 20;
const NEIGHBOR_NODE_SIZE = 15;

const HOVER_DIM_COLOR = "#374151";
const HOVER_PATH_COLOR = "#addb38ff";

const PATH_EDGE_COLOR = PATH_NODE_COLOR;
const NEIGHBOR_EDGE_COLOR = "#496183ff";

/* DOM elements */
const startInput = document.getElementById("startArtist");
const targetInput = document.getElementById("targetArtist");
const playlistNameInput = document.getElementById("playlistName");
const depthInput = document.getElementById("depth");
const resultsDiv = document.getElementById("results");
const spinner = document.getElementById("spinner");
const toggleNeighborsBtn = document.getElementById("toggleNeighborsBtn");
const collapseNeighborsBtn = document.getElementById("collapseNeighborsBtn");
const nodeSelect = document.getElementById("nodeSelect");
const jumpToNodeBtn = document.getElementById("jumpToNodeBtn");
const neighborLimitSlider = document.getElementById("neighborLimit");
const neighborLimitValue = document.getElementById("neighborLimitValue");
const mobileTapBtn = document.getElementById("mobileTapBtn");
const ticker = document.getElementById("searchTicker");
const searchWarning = document.getElementById("searchWarning");

if (ticker) ticker.classList.add("visible");
if (searchWarning) searchWarning.classList.add("visible");
/* ============================================================
   UTILITIES
============================================================ */

function safeTracksFromStep(step) {
  if (!step) return [];
  if (step.track || step.Track) {
    const t = step.track || step.Track;
    return [
      {
        name: t.Name || t.name || "",
        url: t.PhotoURL || t.url || "",
        id: t.ID || "",
        recordingID: t.RecordingID || "",
        recordingName: t.RecordingName || t.recordingName || "",
      },
    ];
  }
  if (Array.isArray(step.tracks)) {
    return step.tracks.map((t) => ({
      name: t.name || "",
      url: t.url || "",
      id: t.id || "",
      recordingID: t.recordingID || "",
      recordingName: t.recordingName || "",
    }));
  }
  if (Array.isArray(step.Tracks)) {
    return step.Tracks.map((t) => ({
      name: t.Name || "",
      url: t.PhotoURL || "",
      id: t.ID || "",
      recordingID: t.RecordingID || "",
      recordingName: t.RecordingName || "",
    }));
  }
  return [];
}

function computeArtistPositionsFromEdges(edges) {
  const pos = new Map();
  let i = 0;
  edges.forEach((e) => {
    if (e.from && !pos.has(e.from)) pos.set(e.from, i++);
    if (e.to && !pos.has(e.to)) pos.set(e.to, i++);
  });
  return pos;
}

function edgeWidth(count, isPath) {
  const c = count || 1;
  return isPath
    ? Math.min(3 + c * 3.5, 32)
    : Math.min(1 + c * 1.1, 18);
}

function hashString(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (h * 31 + str.charCodeAt(i)) | 0;
  }
  return h;
}

function showSpinner() {
  const spinner = document.getElementById("spinner");
  spinner.classList.add("visible");
}

function hideSpinner() {
  const spinner = document.getElementById("spinner");
  spinner.classList.remove("visible");
}

/* ============================================================
   NEIGHBOR LOOKUP / AUTOCOMPLETE
============================================================ */

async function fetchNeighbors(name) {
  try {
    const res = await fetch(`/lookup?name=${encodeURIComponent(name)}`, {
      headers: {
        "X-SDS-Token": window.SDSToken,
      },
    });

    if (!res.ok) {
      const txt = await res.text();
      console.error("Neighbor fetch error:", txt);
      return null;
    }

    const data = await res.json();
    return data;

  } catch (err) {
    console.error("Neighbor fetch error:", err);
    return null;
  }
}

let lastTickerText = "";
let lastWarningText = "";
let tickerInterval = null;

async function updateSearchTicker() {
  const tickerEl = document.getElementById("searchTicker");
  const warningEl = document.getElementById("searchWarning");
  if (!tickerEl || !warningEl) return;

  try {
    const res = await fetch("/api/search/ticker", {
      headers: { "X-SDS-Token": window.SDSToken }
    });
    if (!res.ok) return;

    const data = await res.json();

    const newTickerText = `Searching - ${data.artist}: ${data.count}/${data.max}`;
    const newWarningText = `Depth: ${data.depth} levels`;

    // ------------------------------
    // Only update DOM when changed
    // ------------------------------
    if (newTickerText !== lastTickerText) {
      tickerEl.textContent = newTickerText;
      lastTickerText = newTickerText;
    }

    if (newWarningText !== lastWarningText) {
      warningEl.textContent = newWarningText;
      lastWarningText = newWarningText;
    }

  } catch (err) {
    console.error("ticker error:", err);
  }
}

function startTicker() {
  if (tickerInterval) return;  // already running, don’t start again
  tickerInterval = setInterval(updateSearchTicker, 200);
}

function stopTicker() {
  if (!tickerInterval) return;
  clearInterval(tickerInterval);
  tickerInterval = null;

  // Don't clear the UI — persist last known state
  // ticker stays on screen until a new search resets it
}


async function loadArtistNames() {
  try {
    const res = await fetch("/static/top_artists.txt");
    if (!res.ok) return [];

    const text = await res.text();
    artistNameList = text.split("\n").map(x => x.trim()).filter(Boolean);
    return artistNameList;

  } catch {
    return [];
  }
}

/* ============================================================
   AUTOCOMPLETE UI
============================================================ */

function createAutocomplete(inputEl) {
  const container = inputEl.closest(".autocomplete-container");
  const listEl = container.querySelector(".autocomplete-list");
  let currentIndex = -1;

  function closeList() {
    listEl.style.display = "none";
    listEl.innerHTML = "";
    currentIndex = -1;
  }

  async function updateSuggestions() {
    const q = inputEl.value.trim();
    if (!q) return closeList();
    if (!artistNameList.length) await loadArtistNames();
    const lc = q.toLowerCase();
    const starts = artistNameList.filter((n) =>
      n.toLowerCase().startsWith(lc)
    );
    const contains = artistNameList.filter(
      (n) =>
        !n.toLowerCase().startsWith(lc) &&
        n.toLowerCase().includes(lc)
    );
    const suggestions = [...starts, ...contains].slice(0, 15);
    listEl.innerHTML = "";
    if (!suggestions.length) return closeList();
    suggestions.forEach((name) => {
      const item = document.createElement("div");
      item.className = "autocomplete-item";
      item.setAttribute("role", "option");
      item.innerHTML = `
        <div class="autocomplete-left">
          <div class="artist-badge"></div>
          <div class="autocomplete-name">${name}</div>
        </div>
        <div class="autocomplete-tag">Artist</div>`;
      item.addEventListener("mousedown", (e) => {
        e.preventDefault();
        inputEl.value = name;
        closeList();
      });
      listEl.appendChild(item);
    });
    listEl.style.display = "block";
  }

  inputEl.addEventListener("input", updateSuggestions);
  inputEl.addEventListener("focus", updateSuggestions);
  inputEl.addEventListener("blur", () =>
    setTimeout(closeList, 120)
  );
  inputEl.addEventListener("keydown", (e) => {
    const items = Array.from(
      listEl.querySelectorAll(".autocomplete-item")
    );
    if (!items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      currentIndex = (currentIndex + 1) % items.length;
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      currentIndex =
        (currentIndex - 1 + items.length) % items.length;
    } else if (e.key === "Enter") {
      if (currentIndex >= 0) {
        e.preventDefault();
        inputEl.value =
          items[currentIndex].querySelector(
            ".autocomplete-name"
          ).textContent;
        closeList();
      }
      return;
    } else {
      return;
    }
    items.forEach((item, idx) =>
      item.setAttribute(
        "aria-selected",
        idx === currentIndex
      )
    );
  });
}

loadArtistNames();
createAutocomplete(startInput);
createAutocomplete(targetInput);

/* ============================================================
   NEIGHBOR POSITIONING
============================================================ */

function randomClusterSideForNode(node) {
  if (clusterSideByNode.has(node))
    return clusterSideByNode.get(node);
  const dir = ["left", "right", "up", "down"];
  const s = dir[Math.floor(Math.random() * dir.length)];
  clusterSideByNode.set(node, s);
  return s;
}

function positionNeighborAroundAnchor(anchor, idx, total, side) {
  const attrs = graph.getNodeAttributes(anchor);
  const ax = attrs.x || 0,
    ay = attrs.y || 0;
  const t = total <= 1 ? 0 : idx / (total - 1) - 0.5;
  const radiusBase =
    100 + Math.random() * 35 + Math.log(idx + 2) * 7;
  const jitterRadius = (Math.random() - 0.5) * 12;
  const jitterAngle = (Math.random() - 0.5) * 1.05;
  let baseAngle;
  switch (side) {
    case "left":
      baseAngle = Math.PI;
      break;
    case "right":
      baseAngle = 0;
      break;
    case "up":
      baseAngle = -Math.PI / 2;
      break;
    case "down":
      baseAngle = Math.PI / 2;
      break;
    default:
      baseAngle = Math.random() * Math.PI * 2;
  }
  const spread = 3.1 + Math.random() * 1.35;
  const angle = baseAngle + t * spread + jitterAngle;
  const radius = radiusBase + jitterRadius;
  return {
    x: ax + Math.cos(angle) * radius,
    y: ay + Math.sin(angle) * radius,
  };
}

/* ============================================================
   COSMIC FLOAT
============================================================ */

function startCosmicFloat() {
  if (!renderer || !graph) return;
  if (cosmicAnimationFrame) return;
  const startTime = performance.now();

  function frame(now) {
    const t = (now - startTime) / 1000;
    const amp = 1.2,
      speed = 0.6;
    graph.forEachNode((n, a) => {
      const baseX = a.baseX ?? a.x ?? 0;
      const baseY = a.baseY ?? a.y ?? 0;
      if (a.baseX === undefined || a.baseY === undefined) {
        graph.setNodeAttribute(n, "baseX", baseX);
        graph.setNodeAttribute(n, "baseY", baseY);
      }
      const h = hashString(n);
      const px = ((h & 0xff) / 255) * Math.PI * 2;
      const py = (((h >> 8) & 0xff) / 255) * Math.PI * 2;
      const dx = Math.sin(t * speed + px) * amp;
      const dy = Math.cos(t * speed + py) * amp;
      graph.setNodeAttribute(n, "x", baseX + dx);
      graph.setNodeAttribute(n, "y", baseY + dy);
    });
    renderer.refresh({ skipIndexation: true });
    cosmicAnimationFrame = requestAnimationFrame(frame);
  }

  cosmicAnimationFrame = requestAnimationFrame(frame);
}

function stopCosmicFloat() {
  if (cosmicAnimationFrame) {
    cancelAnimationFrame(cosmicAnimationFrame);
    cosmicAnimationFrame = null;
  }
}

/* ============================================================
   GRAPH INITIALIZATION
============================================================ */

function stopAutoExpansion() {
  if (autoExpandInterval) {
    clearInterval(autoExpandInterval);
    autoExpandInterval = null;
  }
}

function startAutoExpansion() {
  stopAutoExpansion();
  autoExpandInterval = setInterval(async () => {
    if (!graph) return;
    let next = null;
    graph.forEachNode((n, a) => {
      if (next) return;
      const label = a.label || n;
      if (!expandedByNode.has(label)) next = label;
    });
    if (next) await expandNode(next);
    else stopAutoExpansion();
  }, 2000);
}

function initGraph(start, target) {
  const container = document.getElementById("graph");
  if (renderer) {
    renderer.kill();
    renderer = null;
  }
  stopCosmicFloat();
  stopAutoExpansion();
  graph = new Graph();
  container.innerHTML = "";

  // EDGE TOOLTIP
  const tooltip = document.createElement("div");
  tooltip.id = "edge-tooltip";
  tooltip.className = "edge-tooltip";
  container.appendChild(tooltip);

  if (start) {
    graph.addNode(start, {
      label: start,
      size: START_SIZE,
      color: START_COLOR,
      x: 0,
      y: 0,
      baseX: 0,
      baseY: 0,
      role: "path",
      opacity: 1,
      labelColor: "#ffffff",
    });
  }

  renderer = new SigmaLib(graph, container, {
    renderLabels: true,
    renderEdgeLabels: false,
    labelDensity: 0.7,
    labelColor: { attribute: "labelColor", color: "#ffffff" },
    enableEdgeHoverEvents: true,
    zIndex: true,
  });

  refreshNodeDropdown();

  /* ============================================================
     NODE REDUCER
  ============================================================= */
  renderer.setSetting("nodeReducer", (node, data) => {
    const res = { ...data };
    res.opacity = data.opacity ?? 1;

    if (!showNeighbors && data.role === "neighbor") {
      res.hidden = true;
      return res;
    }

    const isHovered = node === reducerState.hoveredNode;
    const isPathHover =
      reducerState.hoveredNode &&
      pathNodeSet.has(reducerState.hoveredNode) &&
      pathEdgeSet.size > 0;

    if (reducerState.hoveredNode) {
      if (isPathHover) {
        if (pathNodeSet.has(node)) {
          res.color = HOVER_PATH_COLOR;
          res.size = data.size * (isHovered ? 1.3 : 1.1);
          res.borderColor = "#ffffff";
          res.borderSize = isHovered ? 3 : 2;
          res.labelColor = isHovered ? "#000000" : "#ffffff";
        } else {
          res.color = HOVER_DIM_COLOR;
          res.size = data.size * 0.7;
          res.label = "";
          res.opacity = 0.35;
        }
        return res;
      }

      const isNeighbor =
        node === reducerState.hoveredNode ||
        reducerState.hoveredNeighbors.has(node);

      if (!isNeighbor) {
        res.color = HOVER_DIM_COLOR;
        res.size = data.size * 0.7;
        res.label = "";
        res.opacity = 0.4;
        return res;
      }

      if (isHovered) {
        res.size = data.size * 1.28;
        res.labelColor = "#000000";
      } else {
        res.labelColor = "#ffffff";
      }

      return res;
    }

    if (data.role === "path") {
      res.borderColor = PATH_EDGE_COLOR;
      res.borderSize = 2;
      res.labelColor = "#ffffff";
    }

    return res;
  });

  /* ============================================================
     EDGE REDUCER
  ============================================================= */
  renderer.setSetting("edgeReducer", (edge, data) => {
    const res = { ...data };

    if (!showNeighbors && data.role === "neighbor") {
      res.hidden = true;
      return res;
    }

    res.opacity = 0.9;
    res.color =
      data.role === "path" ? PATH_EDGE_COLOR : NEIGHBOR_EDGE_COLOR;

    if (reducerState.hoveredNode) {
      const isPathHover =
        pathNodeSet.has(reducerState.hoveredNode) &&
        pathEdgeSet.size > 0;

      if (isPathHover) {
        if (pathEdgeSet.has(edge)) {
          res.color = HOVER_PATH_COLOR;
          res.opacity = 1;
        } else {
          res.hidden = true;
        }
        return res;
      }

      const [src, dst] = graph.extremities(edge);
      const connected =
        src === reducerState.hoveredNode ||
        dst === reducerState.hoveredNode ||
        reducerState.hoveredNeighbors.has(src) ||
        reducerState.hoveredNeighbors.has(dst);

      if (!connected) {
        res.hidden = true;
      }
    }

    return res;
  });

  /* ============================================================
     HOVER / TAP EVENTS
  ============================================================= */
  renderer.on("enterNode", ({ node }) => {
    if (mobileTapMode) return;
    reducerState.hoveredNode = node;
    reducerState.hoveredNeighbors = new Set(graph.neighbors(node));
    renderer.refresh({ skipIndexation: true });
  });

  renderer.on("leaveNode", () => {
    if (mobileTapMode) return;
    reducerState.hoveredNode = null;
    reducerState.hoveredNeighbors.clear();
    renderer.refresh({ skipIndexation: true });
  });

  renderer.on("clickNode", ({ node }) => {
    const label = graph.getNodeAttribute(node, "label") || node;
    toggleNeighbors(label);

    if (!mobileTapMode) return;

    if (tappedNode === node) {
      tappedNode = null;
      reducerState.hoveredNode = null;
      reducerState.hoveredNeighbors.clear();
      renderer.refresh({ skipIndexation: true });
      return;
    }

    tappedNode = node;
    reducerState.hoveredNode = node;
    reducerState.hoveredNeighbors = new Set(graph.neighbors(node));
    renderer.refresh({ skipIndexation: true });
  });

  renderer.on("clickStage", () => {
    if (!mobileTapMode) return;
    tappedNode = null;
    reducerState.hoveredNode = null;
    reducerState.hoveredNeighbors.clear();
    renderer.refresh({ skipIndexation: true });
  });

  /* ============================================================
     TOOLTIP FOLLOW
  ============================================================= */
  renderer.on("mousemove", (e) => {
    const tt = document.getElementById("edge-tooltip");
    if (!tt) return;
    const x = e.event.x + 15 + "px";
    const y = e.event.y + 15 + "px";
    tt.style.left = x;
    tt.style.top = y;
  });

  /* ============================================================
     EDGE HOVER TOOLTIP (TRACKS + IMAGE)
  ============================================================= */
  renderer.on("enterEdge", ({ edge }) => {
    const tt = document.getElementById("edge-tooltip");
    if (!tt) return;

    const attrs = graph.getEdgeAttributes(edge) || {};
    const tracks = Array.isArray(attrs.tracks) ? attrs.tracks : [];
    const [source, target] = graph.extremities(edge);
    const header = `${source} \u2192 ${target}`;

    let listHTML = "";
    if (tracks.length > 0) {
      listHTML = tracks
        .map(
          (t) =>
            `<div class="tt-track">${
              t.recordingName || "Unknown track"
            }</div>`
        )
        .join("");
    } else {
      listHTML =
        "<div class='tt-track'>No track metadata</div>";
    }

    const first = tracks[0] || {};
    const imgHTML = first.url
      ? `<img class="tt-img" src="${first.url}" alt="cover" />`
      : "";

    tt.innerHTML = `
      <div class="tt-wrapper">
        ${imgHTML}
        <div class="tt-info">
          <div class="tt-artists">${header}</div>
          ${listHTML}
        </div>
      </div>
    `;
    tt.style.display = "block";
  });

  renderer.on("leaveEdge", () => {
    const tt = document.getElementById("edge-tooltip");
    if (tt) tt.style.display = "none";
  });

  /* ============================================================
     DRAGGING
  ============================================================= */
  let draggedNode = null;
  let isDragging = false;

  renderer.on("downNode", ({ node }) => {
    draggedNode = node;
    isDragging = true;
  });

  renderer.on("mousemoveBody", (e) => {
    if (!isDragging || !draggedNode) return;
    const pos = renderer.viewportToGraph(e.event);
    graph.setNodeAttribute(draggedNode, "x", pos.x);
    graph.setNodeAttribute(draggedNode, "y", pos.y);
    graph.setNodeAttribute(draggedNode, "baseX", pos.x);
    graph.setNodeAttribute(draggedNode, "baseY", pos.y);
    renderer.refresh({ skipIndexation: true });
  });

  renderer.on("mouseup", () => {
    draggedNode = null;
    isDragging = false;
  });

  startCosmicFloat();
} // END initGraph()

/* ============================================================
   NEIGHBOR EXPANSION LOGIC
============================================================ */

function aggregateNeighbors(arr) {
  const map = new Map();
  if (!Array.isArray(arr)) return [];

  arr.forEach((nb) => {
    if (!nb) return;

    // ALWAYS use the neighbor artist ID
    const key = nb.ID;
    if (!key) return;

    if (!map.has(key)) {
      map.set(key, {
        id: nb.ID,
        name: nb.Name || nb.name || nb.ID,
        tracks: [],
        firstTrack: null,
      });
    }

    const dst = map.get(key);

    const candidates = [
      nb.Tracks,
      nb.tracks,
      Array.isArray(nb.Track) ? nb.Track : null,
      Array.isArray(nb.track) ? nb.track : null,
      nb.Track && !Array.isArray(nb.Track) ? [nb.Track] : null,
      nb.track && !Array.isArray(nb.track) ? [nb.track] : null,
    ].filter(Boolean);

    candidates.forEach((list) => {
      if (!Array.isArray(list)) return;
      list.forEach((t) => {
        if (!t) return;

        const trackObj = {
          name: t.Name || t.name || "",
          url: t.PhotoURL || t.url || "",
          id: t.ID || "",
          recordingID: t.RecordingID || "",
          recordingName: t.RecordingName || t.recordingName || "",
        };

        dst.tracks.push(trackObj);
        if (!dst.firstTrack) dst.firstTrack = trackObj;
      });
    });
  });

  return Array.from(map.values());
}

async function expandNode(anchorName) {
  if (!anchorName || !graph) return;
  anchorName = String(anchorName)
    .replace(/[\$\{\}]/g, "")
    .replace(/\s+/g, " ")
    .trim();

  const entry = await fetchNeighbors(anchorName);

  if (
    !entry ||
    !Array.isArray(entry.Neighbors) ||
    !entry.Neighbors.length
  ) {
    console.warn(`[expandNode] No neighbors for ${anchorName}`);
    return;
  }

  if (!graph.hasNode(anchorName)) {
    const x = Math.random() * 6 - 3;
    const y = Math.random() * 6 - 3;
    graph.addNode(anchorName, {
      label: anchorName,
      size: PATH_NODE_SIZE,
      color: PATH_NODE_COLOR,
      x,
      y,
      baseX: x,
      baseY: y,
      role: "path",
      opacity: 1,
      labelColor: "#ffffff",
    });
  } else {
    graph.setNodeAttribute(anchorName, "role", "path");
    graph.setNodeAttribute(anchorName, "labelColor", "#ffffff");
  }

  let aggregated = aggregateNeighbors(entry.Neighbors).sort(
    (a, b) =>
      (b.tracks?.length || 0) - (a.tracks?.length || 0)
  );

  const limit = parseInt(
    neighborLimitSlider?.value || "999",
    10
  );
  if (aggregated.length > limit)
    aggregated = aggregated.slice(0, limit);

  const createdNodes = [];
  const createdEdges = [];
  const side = randomClusterSideForNode(anchorName);
  const total = aggregated.length;

  aggregated.forEach((agg, idx) => {
    if (!agg) return;

    const nbName = agg.name;
    if (!nbName) return;

    const edgeId = `${anchorName}:::${nbName}`;

    // --- DO NOT OVERWRITE PATH NODES AS NEIGHBORS ---
    const isPathNode = pathNodeSet.has(nbName);

    if (!graph.hasNode(nbName)) {
      const pos = positionNeighborAroundAnchor(
        anchorName,
        idx,
        total,
        side
      );
      graph.addNode(nbName, {
        label: nbName,
        size: NEIGHBOR_NODE_SIZE,
        color: NEIGHBOR_NODE_COLOR,
        x: pos.x,
        y: pos.y,
        baseX: pos.x,
        baseY: pos.y,
        role: "neighbor",
        opacity: 0.85,
        labelColor: "#ffffff",
      });

      if (!isPathNode) {
        createdNodes.push(nbName);
      }
    } else {
      // If this is a path node, do NOT overwrite its styling
      if (!isPathNode) {
        graph.setNodeAttribute(nbName, "role", "neighbor");
        graph.setNodeAttribute(
          nbName,
          "color",
          NEIGHBOR_NODE_COLOR
        );
        graph.setNodeAttribute(
          nbName,
          "size",
          NEIGHBOR_NODE_SIZE
        );
        graph.setNodeAttribute(
          nbName,
          "labelColor",
          "#ffffff"
        );
      }
    }

    const tracks = Array.isArray(agg.tracks)
      ? agg.tracks
      : [];
    const trackCount = tracks.length;
    const first = tracks[0] || {};

    let label;
    if (trackCount === 0) label = "No shared tracks";
    else if (trackCount === 1)
      label = tracks[0].recordingName || "1 track";
    else label = `${trackCount} tracks`;

    const width = edgeWidth(trackCount, false);

    if (!graph.hasEdge(edgeId)) {
      graph.addEdgeWithKey(edgeId, anchorName, nbName, {
        label,
        color: NEIGHBOR_EDGE_COLOR,
        size: width,
        role: "neighbor",
        tracks,
        trackCount,
        trackURL: first.url || "",
      });
      createdEdges.push(edgeId);
    } else {
      graph.setEdgeAttribute(edgeId, "role", "neighbor");
      graph.setEdgeAttribute(edgeId, "label", label);
      graph.setEdgeAttribute(edgeId, "tracks", tracks);
      graph.setEdgeAttribute(
        edgeId,
        "trackCount",
        trackCount
      );
      graph.setEdgeAttribute(
        edgeId,
        "trackURL",
        first.url || ""
      );
      graph.setEdgeAttribute(edgeId, "size", width);
      graph.setEdgeAttribute(
        edgeId,
        "color",
        NEIGHBOR_EDGE_COLOR
      );
    }
  });

  if (createdNodes.length || createdEdges.length) {
    const existing =
      expandedByNode.get(anchorName) || {
        nodes: [],
        edges: [],
      };
    expandedByNode.set(anchorName, {
      nodes: existing.nodes.concat(createdNodes),
      edges: existing.edges.concat(createdEdges),
    });
  }

  if (renderer) {
    refreshNodeDropdown();
    renderer.refresh();
  }
}

function collapseNode(anchorName) {
  const record = expandedByNode.get(anchorName);
  if (!record) return;

  record.edges.forEach((eId) => {
    if (graph.hasEdge(eId)) graph.dropEdge(eId);
  });

  record.nodes.forEach((nId) => {
    if (pathNodeSet.has(nId)) return;
    if (graph.hasNode(nId)) graph.dropNode(nId);
  });

  expandedByNode.delete(anchorName);

  if (renderer) {
    refreshNodeDropdown();
    renderer.refresh();
  }
}

function toggleNeighbors(name) {
  if (!name) return;
  if (expandedByNode.has(name)) collapseNode(name);
  else expandNode(name);
}

function collapseAllNeighbors() {
  Array.from(expandedByNode.keys()).forEach(collapseNode);
  stopAutoExpansion();
}

/* ============================================================
   PATH RENDERING
============================================================ */

function aggregatePath(path) {
  const map = new Map();
  if (!Array.isArray(path)) return [];

  path.forEach((step) => {
    if (!step || !step.from || !step.to) return;
    const key = `${step.from}:::${step.to}`;

    if (!map.has(key)) {
      map.set(key, {
        from: step.from,
        to: step.to,
        tracks: [],
      });
    }

    const edge = map.get(key);
    const tracks = safeTracksFromStep(step);
    tracks.forEach((t) => edge.tracks.push(t));
  });

  return Array.from(map.values());
}

function ensureArtist(name, start, target, posMap) {
  if (!name) return;

  if (graph.hasNode(name)) {
    graph.setNodeAttribute(name, "role", "path");
    graph.setNodeAttribute(name, "labelColor", "#ffffff");

    if (name === start) {
      graph.setNodeAttribute(name, "color", START_COLOR);
      graph.setNodeAttribute(name, "size", START_SIZE);
    } else if (name === target) {
      graph.setNodeAttribute(
        name,
        "color",
        TARGET_COLOR
      );
      graph.setNodeAttribute(
        name,
        "size",
        TARGET_SIZE
      );
    } else {
      graph.setNodeAttribute(
        name,
        "color",
        PATH_NODE_COLOR
      );
      graph.setNodeAttribute(
        name,
        "size",
        PATH_NODE_SIZE
      );
    }
    return;
  }

  let color = PATH_NODE_COLOR;
  let size = PATH_NODE_SIZE;

  if (name === start) {
    color = START_COLOR;
    size = START_SIZE;
  } else if (name === target) {
    color = TARGET_COLOR;
    size = TARGET_SIZE;
  }

  let x = Math.random() * 6 - 3;
  let y = Math.random() * 6 - 3;

  if (posMap && posMap.has(name)) {
    const idx = posMap.get(name);
    const angle = idx * 1.0;
    const radius = 500 + idx * 12;
    x = Math.cos(angle) * radius;
    y = Math.sin(angle) * radius;
  }

  graph.addNode(name, {
    label: name,
    color,
    size,
    x,
    y,
    baseX: x,
    baseY: y,
    role: "path",
    opacity: 1,
    labelColor: "#ffffff",
  });
}

function addPathToGraph(pathSteps, start, target) {
  if (!graph || !renderer || !Array.isArray(pathSteps)) return;

  const aggEdges = aggregatePath(pathSteps);
  window.currentPath = aggEdges;   // <-- the playlist now receives the true final path
  currentPath = aggEdges;

  pathNodeSet.clear();
  pathEdgeSet.clear();

  const posMap = computeArtistPositionsFromEdges(aggEdges);

  aggEdges.forEach((edge) => {
    const from = edge.from;
    const to = edge.to;
    const tracks = edge.tracks || [];
    if (!from || !to) return;

    ensureArtist(from, start, target, posMap);
    ensureArtist(to, start, target, posMap);

    const trackCount = tracks.length || 1;
    const edgeId = `${from}:::${to}`;
    pathNodeSet.add(from);
    pathNodeSet.add(to);
    pathEdgeSet.add(edgeId);

    const label =
      trackCount === 1
        ? tracks[0].name || "1 track"
        : `${trackCount} tracks`;

    const width = edgeWidth(trackCount, true);
    const first = tracks[0] || {};

    if (graph.hasEdge(edgeId)) {
      graph.setEdgeAttribute(edgeId, "role", "path");
      graph.setEdgeAttribute(edgeId, "tracks", tracks);
      graph.setEdgeAttribute(
        edgeId,
        "trackCount",
        trackCount
      );
      graph.setEdgeAttribute(
        edgeId,
        "trackURL",
        first.url || ""
      );
      graph.setEdgeAttribute(edgeId, "size", width);
      graph.setEdgeAttribute(edgeId, "label", label);
      graph.setEdgeAttribute(
        edgeId,
        "color",
        PATH_EDGE_COLOR
      );
    } else {
      graph.addEdgeWithKey(edgeId, from, to, {
        role: "path",
        tracks: tracks,
        trackCount: trackCount,
        trackURL: first.url || "",
        size: width,
        label: label,
        color: PATH_EDGE_COLOR,
      });
    }
  });

  refreshNodeDropdown();
  renderer.refresh();
}
function showTicker() {
  document.getElementById("searchTicker").classList.add("visible");
  document.getElementById("searchWarning").classList.add("visible");
}

function hideTicker() {
  document.getElementById("searchTicker").classList.remove("visible");
  document.getElementById("searchWarning").classList.remove("visible");
}

/* ============================================================
   ASYNC SEARCH WORKFLOW
============================================================ */

async function runSearch() {
  const start = startInput.value.trim();
  const target = targetInput.value.trim();
  const depth = Number(depthInput.value || -1);

  if (!start || !target) {
    resultsDiv.innerHTML =
      "<p class='error'>Start and Target are required.</p>";
    return;
  }

  // Reset graph & state
  expandedByNode.clear();
  pathNodeSet.clear();
  pathEdgeSet.clear();
  clusterSideByNode.clear();
  stopAutoExpansion();
  initGraph(start, target);

  resultsDiv.innerHTML = "";

  // --- SHOW SPINNER ---
  spinner.classList.add("visible");
  showTicker(); 
  // --- STEP 1: Start job ---
  let jobID;
  try {
    if (!window.SDSToken) {
      throw new Error("Missing SDS token on client side.");
    }

    const res = await fetch("/api/search/start", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-SDS-Token": window.SDSToken,
      },
      body: JSON.stringify({ start, target, depth }),
    });

    if (!res.ok) {
      spinner.classList.remove("visible");   // HIDE spinner on error
      const text = await res.text();
      showError(`Search start failed:\n${text}`);
      return;
    }

    const data = await res.json();
    jobID = data.jobID;

    startAutoExpansion();

  } catch (err) {
    spinner.classList.remove("visible"); // HIDE spinner on catch
    showError("Search request error:\n" + err.message);
    return;
  }

  // --- STEP 2: Poll until BFS finishes ---
  pollJob(jobID);
}


async function pollJob(jobID) {
  const interval = setInterval(async () => {
    let job;

    try {
      const res = await fetch(`/api/search/status?jobID=${jobID}`, {
        headers: { "X-SDS-Token": window.SDSToken },
      });

      if (!res.ok) return;

      job = await res.json();
      console.log("JOB RESPONSE:", job);

    } catch (err) {
      console.error("Polling error:", err);
      return;
    }

    // -------------------------------
    // Still running
    // -------------------------------
    if (job.status === "running") {
      showTicker();                            // ensure ticker stays visible
      startTicker();
      return;
    }

    // -------------------------------
    // Error
    // -------------------------------
    if (job.status === "error") {
      clearInterval(interval);
      spinner.classList.remove("visible");
      hideTicker();                            // hide when finished
      showError(job.error || "Unknown search error.");
      return;
    }

    // -------------------------------
    // Finished
    // -------------------------------
    if (job.status === "finished") {
      clearInterval(interval);
      spinner.classList.remove("visible");
      hideTicker();
      stopTicker();

      const result = job.result;
      window.currentPath = result.path;
      window.currentJobID = jobID;     // FIXED
      renderFinalResult(result);
    }
  }, 1000);
}

function renderFinalResult(result) {
  const { start, target, hops, path } = result;

  let html = `<p class='muted-strong'><strong>Start:</strong> ${start}<br>
              <strong>Target:</strong> ${target}<br>
              <strong>Hops:</strong> ${hops}</p>`;

  if (Array.isArray(path) && path.length > 0) {
    html += `<ol>`;
    path.forEach((step) => {
      const from = step.from || "";
      const to = step.to || "";
      const tracks = safeTracksFromStep(step);

      const trackList = tracks.length
        ? tracks.map(t => t.recordingName || "Unknown").join(", ")
        : "No track metadata";

      html += `<li>${from} — [${trackList}] → ${to}</li>`;
    });
    html += `</ol>`;
  }

  resultsDiv.innerHTML = html;

  addPathToGraph(path, start, target);
  stopAutoExpansion();

  const cam = renderer.getCamera();
  cam.animate({ x: 0, y: 0, ratio: 0.35 }, { duration: 800 });
}



/* ============================================================
   AUTH & PLAYLIST LOGIC
============================================================ */

// Called when user clicks "Create Playlist"
function startAuthAndPlaylist() {
  // Open Spotify OAuth window
  const win = window.open("/auth", "_blank", "width=600,height=800");

  function handleAuth(event) {
    if (!event.data || event.data.auth !== "done") return;

    window.removeEventListener("message", handleAuth);

    if (win && !win.closed) win.close();

    const playlistName =
      playlistNameInput.value.trim() ||
      `SixDegreeSpotify: ${startInput.value.trim()} → ${targetInput.value.trim()}`;

    createPlaylist(playlistName);
  }

  window.addEventListener("message", handleAuth);
}

async function createPlaylist() {
  if (!window.currentPath || window.currentPath.length === 0) {
    alert("No path to create playlist from.");
    return;
  }

  if (!window.currentJobID) {
    alert("No search job found — run a search first.");
    return;
  }

  const playlistName =
    playlistNameInput.value.trim() ||
    `SixDegreeSpotify: ${startInput.value} → ${targetInput.value}`;

  try {
    const res = await fetch("/createPlaylist", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-SDS-Token": window.SDSToken,
      },
      body: JSON.stringify({
        playlistName,
        jobID: window.currentJobID,
      }),
    });

    const data = await res.json();

    // 🔥 If Spotify login is required
    if (data.auth_required) {
      window.location = data.auth_url;  // redirect user to Spotify fOAuth
      return;
    }

    if (!res.ok) {
      alert("Playlist creation failed:\n" + JSON.stringify(data));
      return;
    }

    // SUCCESS
    if (data.url) {
      if (confirm("Playlist created! Open in Spotify?")) {
        window.open(data.url, "_blank");
      }
    } else {
      alert("Playlist created, but no playlist URL returned.");
    }

  } catch (err) {
    alert("Playlist creation error:\n" + err.message);
  }
}

function showError(msg) {
  if (!resultsDiv) return;
  resultsDiv.innerHTML = `
    <div class="error-box">
      <strong>Error</strong><br>
      <pre>${msg}</pre>
    </div>
  `;
  spinner.style.display = "none";
}

function showInfo(msg) {
  if (!resultsDiv) return;
  resultsDiv.innerHTML = `
    <div class="info-box">
      ${msg}
    </div>
  `;
}

/* ============================================================
   DROPDOWN / CAMERA
============================================================ */

function refreshNodeDropdown() {
  if (!graph) return;
  const names = [];
  graph.forEachNode((n, a) =>
    names.push(a.label || n)
  );
  names.sort((a, b) => a.localeCompare(b));

  nodeSelect.innerHTML =
    `<option value="">Jump to node…</option>` +
    names.map((n) => `<option>${n}</option>`).join("");
}

function jumpToNode(name) {
  if (!renderer || !graph || !name) return;
  if (!graph.hasNode(name)) return;

  const cam = renderer.getCamera();
  const pos = renderer.getNodeDisplayData(name);
  if (!pos) return;

  cam.animate(
    { x: pos.x, y: pos.y, ratio: 0.25 },
    { duration: 650 }
  );
}

/* ============================================================
   EVENT LISTENERS
============================================================ */

document
  .getElementById("searchForm")
  .addEventListener("submit", (e) => {
    e.preventDefault();
    runSearch();
  });

toggleNeighborsBtn.addEventListener("click", () => {
  showNeighbors = !showNeighbors;
  toggleNeighborsBtn.textContent = showNeighbors
    ? "Hide Neighbors"
    : "Show Neighbors";
  if (renderer)
    renderer.refresh({ skipIndexation: true });
});

collapseNeighborsBtn.addEventListener("click", () => {
  collapseAllNeighbors();
});

jumpToNodeBtn.addEventListener("click", () => {
  const name = nodeSelect.value;
  if (name) jumpToNode(name);
});

neighborLimitSlider.addEventListener("input", () => {
  neighborLimitValue.textContent = neighborLimitSlider.value;
});

mobileTapBtn.addEventListener("click", () => {
  mobileTapMode = !mobileTapMode;
  mobileTapBtn.textContent = mobileTapMode
    ? "Mobile Tap Mode: ON"
    : "Mobile Tap Neighbor Mode";

  renderer?.setSetting("enableHovering", !mobileTapMode);

  if (!mobileTapMode) {
    tappedNode = null;
    reducerState.hoveredNode = null;
    reducerState.hoveredNeighbors.clear();
    renderer?.refresh({ skipIndexation: true });
  }
});

document.addEventListener("DOMContentLoaded", () => {
  const arrow = document.querySelector(".arrow");
  if (arrow) {
    arrow.addEventListener("click", () => {
      window.open("https://buymeacoffee.com/jmurillo", "_blank");
    });
  }
});


/* ============================================================
   INITIALIZE EMPTY GRAPH ON LOAD
============================================================ */

initGraph("", "");

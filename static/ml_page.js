/**
 * ML Page JavaScript
 * Handles dynamic table rendering, collapsible sections, and data management
 */

class GenericDataTable {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.data = null;
  }

  /**
   * Detect the format of the data and render accordingly
   */
  render(data) {
    this.data = data;
    this.container.innerHTML = '';

    if (!data) {
      this.renderEmpty();
      return;
    }

    // Detect data format
    if (Array.isArray(data)) {
      if (data.length === 0) {
        this.renderEmpty();
      } else if (typeof data[0] === 'object' && data[0] !== null) {
        // Array of objects - render as table
        this.renderArrayOfObjects(data);
      } else {
        // Array of primitives
        this.renderArrayOfPrimitives(data);
      }
    } else if (typeof data === 'object' && data !== null) {
      // Single object - render as key-value pairs
      this.renderObject(data);
    } else {
      // Primitive value
      this.renderPrimitive(data);
    }
  }

  /**
   * Render array of objects as a table
   */
  renderArrayOfObjects(data) {
    const table = document.createElement('table');

    // Extract all unique keys from all objects
    const allKeys = new Set();
    data.forEach(obj => {
      Object.keys(obj).forEach(key => allKeys.add(key));
    });
    const headers = Array.from(allKeys);

    // Create header
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    headers.forEach(header => {
      const th = document.createElement('th');
      th.textContent = this.formatHeader(header);
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Create body
    const tbody = document.createElement('tbody');
    data.forEach(row => {
      const tr = document.createElement('tr');
      headers.forEach(header => {
        const td = document.createElement('td');
        const value = row[header];
        td.innerHTML = this.formatValue(value);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    this.container.appendChild(table);
  }

  /**
   * Render array of primitives
   */
  renderArrayOfPrimitives(data) {
    const table = document.createElement('table');

    // Create header
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    const th1 = document.createElement('th');
    th1.textContent = 'Index';
    const th2 = document.createElement('th');
    th2.textContent = 'Value';
    headerRow.appendChild(th1);
    headerRow.appendChild(th2);
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Create body
    const tbody = document.createElement('tbody');
    data.forEach((value, index) => {
      const tr = document.createElement('tr');

      const tdIndex = document.createElement('td');
      tdIndex.innerHTML = `<span class="value-number">${index}</span>`;
      tr.appendChild(tdIndex);

      const tdValue = document.createElement('td');
      tdValue.innerHTML = this.formatValue(value);
      tr.appendChild(tdValue);

      tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    this.container.appendChild(table);
  }

  /**
   * Render single object as key-value pairs
   */
  renderObject(data) {
    const table = document.createElement('table');

    // Create header
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    const th1 = document.createElement('th');
    th1.textContent = 'Property';
    const th2 = document.createElement('th');
    th2.textContent = 'Value';
    headerRow.appendChild(th1);
    headerRow.appendChild(th2);
    thead.appendChild(headerRow);
    table.appendChild(thead);

    // Create body
    const tbody = document.createElement('tbody');
    Object.entries(data).forEach(([key, value]) => {
      const tr = document.createElement('tr');

      const tdKey = document.createElement('td');
      tdKey.innerHTML = `<strong>${this.formatHeader(key)}</strong>`;
      tr.appendChild(tdKey);

      const tdValue = document.createElement('td');
      tdValue.innerHTML = this.formatValue(value);
      tr.appendChild(tdValue);

      tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    this.container.appendChild(table);
  }

  /**
   * Render primitive value
   */
  renderPrimitive(data) {
    const div = document.createElement('div');
    div.className = 'empty-state';
    div.innerHTML = this.formatValue(data);
    this.container.appendChild(div);
  }

  /**
   * Render empty state
   */
  renderEmpty() {
    const div = document.createElement('div');
    div.className = 'empty-state';
    div.innerHTML = `
      <div class="empty-state-icon">📊</div>
      <p>No data available</p>
      <p style="font-size: 0.8rem; margin-top: 0.5rem;">
        Perform a search to see results here
      </p>
    `;
    this.container.appendChild(div);
  }

  /**
   * Render loading state
   */
  renderLoading() {
    this.container.innerHTML = `
      <div class="loading-state">
        <div class="spinner"></div>
        <p>Loading data...</p>
      </div>
    `;
  }

  /**
   * Format header text
   */
  formatHeader(text) {
    return text
      .replace(/_/g, ' ')
      .replace(/([A-Z])/g, ' $1')
      .trim()
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join(' ');
  }

  /**
   * Format value based on type with color coding
   */
  formatValue(value) {
    if (value === null) {
      return '<span class="value-null">null</span>';
    }

    if (value === undefined) {
      return '<span class="value-null">undefined</span>';
    }

    if (typeof value === 'boolean') {
      return `<span class="value-boolean">${value}</span>`;
    }

    if (typeof value === 'number') {
      return `<span class="value-number">${value.toLocaleString()}</span>`;
    }

    if (typeof value === 'string') {
      // Check if it's a URL
      if (value.match(/^https?:\/\//)) {
        return `<a href="${value}" target="_blank" class="value-string">${value}</a>`;
      }
      return `<span class="value-string">${this.escapeHtml(value)}</span>`;
    }

    if (Array.isArray(value)) {
      if (value.length === 0) {
        return '<span class="value-array">[]</span>';
      }
      return `<span class="value-array">[${value.length} items]</span>`;
    }

    if (typeof value === 'object') {
      const keys = Object.keys(value);
      if (keys.length === 0) {
        return '<span class="value-object">{}</span>';
      }
      return `<span class="value-object">{${keys.length} properties}</span>`;
    }

    return this.escapeHtml(String(value));
  }

  /**
   * Escape HTML to prevent XSS
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Clear the table
   */
  clear() {
    this.data = null;
    this.renderEmpty();
  }
}

class CollapsibleSection {
  constructor(headerId, containerId, buttonId) {
    this.header = document.getElementById(headerId);
    this.container = document.getElementById(containerId);
    this.button = document.getElementById(buttonId);
    this.isCollapsed = false;

    this.init();
  }

  init() {
    // Click on header or button to toggle
    this.header.addEventListener('click', () => this.toggle());
    this.button.addEventListener('click', (e) => {
      e.stopPropagation();
      this.toggle();
    });
  }

  toggle() {
    this.isCollapsed = !this.isCollapsed;

    if (this.isCollapsed) {
      this.container.classList.add('collapsed');
      this.button.textContent = '+';
    } else {
      this.container.classList.remove('collapsed');
      this.button.textContent = '−';
    }
  }

  expand() {
    this.isCollapsed = false;
    this.container.classList.remove('collapsed');
    this.button.textContent = '−';
  }

  collapse() {
    this.isCollapsed = true;
    this.container.classList.add('collapsed');
    this.button.textContent = '+';
  }
}

function normalizeNeighborsResponse(response) {
  console.log('[normalizeNeighborsResponse] Full input:', response);
  
  if (!response || typeof response !== 'object') return [];
  
  // Normalize root-level fields
  const artistName = response.name || response.Name || 
    response.src_artist_name || 
    response.SrcArtistName ||
    response.srcartistname ||
    'Unknown Artist';
    
  const neighbors = response.Neighbors || response.neighbors || [];
  
  console.log('[normalizeNeighborsResponse] Artist name:', artistName);
  console.log('[normalizeNeighborsResponse] Neighbors:', neighbors);
  
  if (!Array.isArray(neighbors)) return [];
  
  return neighbors.map((n, idx) => {
    console.log(`[normalizeNeighborsResponse] Neighbor ${idx}:`, n);
    console.log(`  - n.name: ${n.name}`);
    console.log(`  - n.Name: ${n.Name}`);
    console.log(`  - n.tracks: ${n.tracks}`);
    console.log(`  - n.Tracks: ${n.Tracks}`);
    
    const featuredWith = n.Name || n.name || n.artistName || 
                        n.dst_artist_name || n.DstArtistName ||
                        n.dstartistname || n.resolvedName || 'Unknown';
    
    console.log(`  - Final featuredWith: ${featuredWith}`);
    
    return {
      artistName,
      featuredWith: featuredWith,
      numberOfTracks: Array.isArray(n.Tracks || n.tracks)
        ? (n.Tracks || n.tracks).length
        : 0,
      prob: n.probability ?? n.Probability ?? null,
      tracks: n.Tracks || n.tracks || [],
      srcArtistId: n.srcArtistId || null,
      dstArtistId: n.dstArtistId || null,
    };
  });
}

/**
 * Normalize a name for fuzzy comparison:
 * lowercase, strip parenthesized/bracketed suffixes, collapse whitespace.
 */
function normalizeName(name) {
  return (name || '')
    .toLowerCase()
    .replace(/\s*[\(\[].*?[\)\]]\s*/g, ' ')   // remove (Spanglish), [Remix], etc.
    .replace(/[^\w\s]/g, '')                    // strip punctuation
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Check whether two names are "similar enough" to be considered the same item.
 * Returns true if, after normalization, one is a prefix of the other
 * or they share a high overlap.
 */
function areSimilarNames(a, b) {
  const na = normalizeName(a);
  const nb = normalizeName(b);
  if (!na || !nb) return false;
  if (na === nb) return true;
  const shorter = na.length <= nb.length ? na : nb;
  const longer  = na.length <= nb.length ? nb : na;
  return longer.startsWith(shorter);
}

/**
 * Deduplicate tracks within a single row by similar name.
 * Among similar tracks, prefer the one that has actual audio features.
 */
function deduplicateTracksByName(tracks) {
  if (!Array.isArray(tracks) || tracks.length === 0) return tracks;

  const groups = [];         // Array of { representative, tracks[] }

  for (const track of tracks) {
    const tName = track.recordingName || track.RecordingName || track.name || track.Name || '';
    let matched = false;
    for (const group of groups) {
      const gName = group.representative.recordingName ||
                    group.representative.RecordingName ||
                    group.representative.name ||
                    group.representative.Name || '';
      if (areSimilarNames(tName, gName)) {
        group.tracks.push(track);
        matched = true;
        break;
      }
    }
    if (!matched) {
      groups.push({ representative: track, tracks: [track] });
    }
  }

  // For each group pick the best: prefer a track that has features
  return groups.map(g => {
    const withFeatures = g.tracks.filter(t => hasTrackFeatures(t));
    return withFeatures.length > 0 ? withFeatures[0] : g.tracks[0];
  });
}

/**
 * Returns true if a track object contains actual audio features
 * (i.e. it was successfully enriched from trackLookup).
 */
function hasTrackFeatures(track) {
  // These are feature fields returned by the backend; if any exist the track was enriched
  const featureKeys = [
    'mood_acoustic', 'mood_aggressive', 'mood_electronic', 'mood_happy',
    'mood_party', 'mood_relaxed', 'mood_sad', 'timbre', 'gender',
    'genre_dortmund', 'genre_electronic', 'genre_rosamerica', 'genre_tzanetakis',
    'voice_instrumental', 'danceability', 'tonal_atonal',
    'ismir04_rhythm', 'recording_name', 'recording_gid',
  ];
  return featureKeys.some(k => track[k] !== undefined && track[k] !== null && track[k] !== '');
}

/**
 * Deduplicate neighbors (rows) by similar artist name.
 * Keeps one representative per cluster of similar names.
 */
function deduplicateNeighborsByName(neighbors) {
  if (!Array.isArray(neighbors) || neighbors.length === 0) return neighbors;

  const groups = [];

  for (const n of neighbors) {
    const nName = n.Name || n.name || '';
    let matched = false;
    for (const group of groups) {
      const gName = group.representative.Name || group.representative.name || '';
      if (areSimilarNames(nName, gName)) {
        group.items.push(n);
        matched = true;
        break;
      }
    }
    if (!matched) {
      groups.push({ representative: n, items: [n] });
    }
  }

  // Keep the first representative from each group
  return groups.map(g => g.representative);
}

/**
 * Format neighbors data from API response
 * Expected format: { Name: string, Neighbors: Array }
 */
function formatNeighborsData(data) {
  // Handle both lowercase and capitalized keys
  const neighbors = data.Neighbors || data.neighbors;
  const artistName = data.Name || data.name || data.artistName || data.src_artist_name || data.SrcArtistName || data.srcartistname;

  if (!neighbors || !Array.isArray(neighbors)) {
    return [];
  }

  return neighbors.map(neighbor => ({
    artistName: artistName || 'Unknown Artist',
    featuredWith: neighbor.Name || neighbor.name || neighbor.artistName || neighbor.dst_artist_name || neighbor.DstArtistName || neighbor.dstartistname || 'Unknown',
    numberOfTracks: (neighbor.Tracks || neighbor.tracks || []).length,
    tracks: neighbor.Tracks || neighbor.tracks || [],
    prob: neighbor.probability || neighbor.Probability || "Unknown"
  }));
}

/**
 * Render collaboration table with expandable track listings
 */
function renderCollaborationTable(tableInstance, data) {
  tableInstance.container.innerHTML = '';

  if (!data || data.length === 0) {
    tableInstance.renderEmpty();
    return;
  }

  // List of the potential columns that will be added to the table
  const columns = [
    { key: 'artist', label: 'Artist Name' },
    { key: 'neighbor', label: 'Featured With' },
    { key: 'probability', label: 'Probability' },
    { key: 'tracks', label: 'Number of Tracks' }
  ];

  const table = document.createElement('table');
  table.className = 'collaboration-table';

  // Create header
  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');

  ['Artist Name', 'Featured With', 'Number of Tracks', ''].forEach(headerText => {
    const th = document.createElement('th');
    th.textContent = headerText;
    headerRow.appendChild(th);
  });

  thead.appendChild(headerRow);
  table.appendChild(thead);

  // Create body
  const tbody = document.createElement('tbody');

  data.forEach((row, index) => {
    // Main row
    const tr = document.createElement('tr');
    tr.className = 'collaboration-row';

    // Artist Name
    const tdArtist = document.createElement('td');
    tdArtist.textContent = row.artistName;
    tr.appendChild(tdArtist);

    // Featured With
    const tdFeatured = document.createElement('td');
    tdFeatured.textContent = row.featuredWith;
    tr.appendChild(tdFeatured);

    // Number of Tracks
    const tdCount = document.createElement('td');
    tdCount.textContent = row.numberOfTracks;
    tr.appendChild(tdCount);

    // Dropdown Button
    const tdButton = document.createElement('td');
    const button = document.createElement('button');
    button.className = 'dropdown-btn';
    button.textContent = '▼';
    button.dataset.index = index;

    // Only add button if there are tracks to show
    if (row.tracks && row.tracks.length > 0) {
      button.addEventListener('click', () => {
        const detailRow = document.getElementById(`detail-row-${index}`);
        if (detailRow) {
          const isVisible = detailRow.style.display !== 'none';
          detailRow.style.display = isVisible ? 'none' : 'table-row';
          button.textContent = isVisible ? '▼' : '▲';
        }
      });
      tdButton.appendChild(button);
    } else {
      tdButton.textContent = '-';
    }

    tr.appendChild(tdButton);
    tbody.appendChild(tr);

    // Detail row for tracks (initially hidden)
    if (row.tracks && row.tracks.length > 0) {
      const detailTr = document.createElement('tr');
      detailTr.id = `detail-row-${index}`;
      detailTr.className = 'detail-row';
      detailTr.style.display = 'none';

      const detailTd = document.createElement('td');
      detailTd.colSpan = 4;

      const trackList = document.createElement('div');
      trackList.className = 'track-list';

      const trackHeader = document.createElement('h4');
      trackHeader.textContent = 'Tracks:';
      trackList.appendChild(trackHeader);

      const ul = document.createElement('ul');
      row.tracks.forEach(track => {
        const li = document.createElement('li');

        // Handle different track data formats
        // API returns: { name, recordingName, photoURL }
        const trackName = track.recordingName || track.name || track.trackName || track.title || 'Unknown Track';
        const connection = track.connection || track.isConnection || false;

        li.innerHTML = `
          <span class="track-name">${escapeHtml(trackName)}</span>
          ${connection ? '<span class="connection-badge">Connection: True</span>' : ''}
        `;

        ul.appendChild(li);
      });

      trackList.appendChild(ul);
      detailTd.appendChild(trackList);
      detailTr.appendChild(detailTd);
      tbody.appendChild(detailTr);
    }
  });

  table.appendChild(tbody);
  tableInstance.container.appendChild(table);
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Show error message to user
 */
function showError(message) {
  alert(message);
  console.error(message);
}

/**
 * Poll BFS job status
 */
function pollJob(jobID) {
  const pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/search/status?jobID=${encodeURIComponent(jobID)}`, {
        headers: {
          'X-SDS-Token': window.SDSToken
        }
      });

      if (!res.ok) {
        clearInterval(pollInterval);
        console.error('Poll failed');
        const spinner = document.getElementById('spinner');
        if (spinner) spinner.classList.remove('visible');
        return;
      }

      const data = await res.json();

      if (data.status === 'complete') {
        clearInterval(pollInterval);
        const spinner = document.getElementById('spinner');
        if (spinner) spinner.classList.remove('visible');

        console.log('BFS search complete:', data);

        // Display the path if found
        if (data.path) {
          displaySearchPath(data.path);
        } else if (data.message) {
          alert(data.message);
        }
      } else if (data.status === 'failed') {
        clearInterval(pollInterval);
        const spinner = document.getElementById('spinner');
        if (spinner) spinner.classList.remove('visible');
        showError('Search failed: ' + (data.error || 'Unknown error'));
      }

    } catch (err) {
      clearInterval(pollInterval);
      console.error('Polling error:', err);
      const spinner = document.getElementById('spinner');
      if (spinner) spinner.classList.remove('visible');
    }
  }, 1000); // Poll every second
}

/**
 * Display the BFS search path result
 */
function displaySearchPath(path) {
  if (!path || path.length === 0) {
    alert('No path found between the artists');
    return;
  }
  
  // Create a simple display - you can customize this
  const pathString = path.join(' → ');
  alert(`Path found (${path.length} steps):\n\n${pathString}`);
  
  // Optionally, you could display this in a dedicated section on the page
  console.log('Path:', path);
}

/**
 * Start auto-expansion if needed (placeholder)
 */
function startAutoExpansion() {
  // Implement if you have auto-expansion logic
  console.log('Auto-expansion started');
}

/**
 * Fetch with retry logic - keeps retrying until data has neighbors or timeout.
 * Used by Step 2 for artist neighbor lookups.
 * @param {string} url - The URL to fetch
 * @param {number} timeout - Maximum time to retry in milliseconds
 * @param {number} retryInterval - Time between retries in milliseconds
 * @returns {Promise<Object>} - The fetched data
 */
async function fetchWithRetry(url, timeout, retryInterval) {
  const startTime = Date.now();
  const headers = { 'X-SDS-Token': window.SDSToken };

  while (Date.now() - startTime < timeout) {
    try {
      const response = await fetch(url, { headers });
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();

      const neighbors = data.Neighbors || data.neighbors;
      if (data && neighbors && Array.isArray(neighbors) && neighbors.length > 0) {
        console.log(`Successfully fetched data with ${neighbors.length} neighbors`);
        return data;
      }

      console.log('No neighbors found yet, retrying...', data);
      await new Promise(resolve => setTimeout(resolve, retryInterval));
    } catch (error) {
      console.error('Fetch error:', error);
      await new Promise(resolve => setTimeout(resolve, retryInterval));
    }
  }

  // Timeout reached - make one final attempt
  console.log('Timeout reached, making final fetch attempt');
  const response = await fetch(url, { headers });
  if (!response.ok) {
    throw new Error(`Failed to fetch data: ${response.status}`);
  }
  return await response.json();
}

/**
 * SynthManager — manages synthetic data fetching with caching, cancellation, and polling.
 * Replaces pollUntilData for Step 5.
 */
class SynthManager {
  constructor() {
    /** @type {Map<string, object>} cacheKey -> synthData */
    this._cache = new Map();
    /** @type {AbortController|null} */
    this._controller = null;
    /** @type {boolean} */
    this._polling = false;
  }

  /** Cancel any in-flight poll. Safe to call even if nothing is running. */
  cancel() {
    if (this._controller) {
      this._controller.abort();
      this._controller = null;
    }
    this._polling = false;
  }

  /**
   * Check if we have cached results for a given key.
   * @param {string} srcId
   * @param {string|null} dstId
   * @returns {object|null}
   */
  getCached(srcId, dstId) {
    const key = dstId ? `${srcId}::${dstId}` : srcId;
    return this._cache.get(key) || null;
  }

  /**
   * Fetch synthetic neighbor data with polling, cancellation, and caching.
   * Returns cached data immediately if available; otherwise polls the backend
   * (which checks DB cache before calling the ML service).
   *
   * @param {string} srcId        Source artist MBID
   * @param {string|null} dstId   Destination artist MBID (optional)
   * @param {object} options
   * @param {number} [options.limit=100] Number of neighbors to fetch
   * @param {number} [options.intervalMs=5000]
   * @param {number} [options.timeoutMs=360000]
   * @returns {Promise<object>} synthData
   * @throws {DOMException} AbortError if cancelled
   */
  async fetch(srcId, dstId, { limit = 100, intervalMs = 5000, timeoutMs = 360000 } = {}) {
    // 1. Cancel any previous poll
    this.cancel();

    // 2. Check client-side cache
    const cacheKey = dstId ? `${srcId}::${dstId}` : srcId;
    const cached = this._cache.get(cacheKey);
    if (cached) {
      console.log('[SynthManager] Client cache hit for', cacheKey);
      return cached;
    }

    // 3. Build URL with limit param
    let url = `/ml/synth/artist?src=${encodeURIComponent(srcId)}&limit=${limit}`;
    // if (dstId) {
    //   url += `&dst=${encodeURIComponent(dstId)}`;
    // }

    // 4. Start polling with AbortController
    this._controller = new AbortController();
    const signal = this._controller.signal;
    this._polling = true;

    const startTime = Date.now();
    const headers = { 'X-SDS-Token': window.SDSToken };

    while (this._polling) {
      if (signal.aborted) {
        throw new DOMException('Synth fetch aborted', 'AbortError');
      }

      if (Date.now() - startTime > timeoutMs) {
        this.cancel();
        throw new Error('SynthManager: polling timeout — no valid data received');
      }

      try {
        const response = await fetch(url, { headers, signal });
        if (!response.ok) {
          const errBody = await response.text().catch(() => '(no body)');
          console.error(`[SynthManager] HTTP ${response.status} from backend:`, errBody);
          throw new Error(`HTTP error! status: ${response.status} — ${errBody}`);
        }
        const data = await response.json();

        // Backend returns {"status":"pending"} while the ML service is still
        // working on the first request. Just keep polling — the result will
        // land in the DB cache and the next poll will return it.
        if (data.status === 'pending') {
          console.log('[SynthManager] ML prediction in progress, polling again...');
        } else {
          const neighbors = data.neighbors || data.Neighbors;
          if (data && neighbors && Array.isArray(neighbors) && neighbors.length > 0) {
            console.log(`[SynthManager] Got ${neighbors.length} neighbors for ${cacheKey}`);
            this._cache.set(cacheKey, data);
            this._polling = false;
            this._controller = null;
            return data;
          }
          console.log('[SynthManager] No neighbors yet, polling again...');
        }
      } catch (err) {
        if (err.name === 'AbortError') {
          console.log('[SynthManager] Fetch aborted for', cacheKey);
          throw err;
        }
        console.error('[SynthManager] Fetch error:', err);
      }

      // Wait before next poll, aborting the sleep if cancelled
      await new Promise((resolve, reject) => {
        const timer = setTimeout(resolve, intervalMs);
        signal.addEventListener('abort', () => {
          clearTimeout(timer);
          reject(new DOMException('Synth fetch aborted', 'AbortError'));
        }, { once: true });
      });
    }
  }

  /** Clear all cached results. */
  clearCache() {
    this._cache.clear();
  }
}


// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
  // --- Tables ---
  const table1 = new MLDataTable('table1');
  const table2 = new MLDataTable('table2');
  const synthManager = new SynthManager();

  // --- Collapsible sections ---
  const section1 = new CollapsibleSection('table1Header', 'table1Container', 'collapse1');
  const section2 = new CollapsibleSection('table2Header', 'table2Container', 'collapse2');

  // --- Saved connections panel ---
  const savedPanel = new SavedConnectionsPanel();
  window._savedPanel = savedPanel;
  savedPanel.refresh(); // Show any previously saved connections from localStorage

  // --- UI elements (shared with graph page) ---
  const mlStartInput = document.getElementById('startArtist');
  const mlTargetInput = document.getElementById('targetArtist');

  // --- destIndicator ---
  let providedDestArtist = true;

  // Initial empty state
  table1.renderEmpty();
  table2.renderEmpty();

  // --- Exported ML analysis function (called from app_v2.js via search mode) ---
  window.runMLAnalysis = async function() {
    // Cancel any in-flight synth poll from a previous search
    synthManager.cancel();

    const targetArtist = mlStartInput.value.trim();
    let destArtist = mlTargetInput.value.trim();
    const searchId = `${targetArtist}::${destArtist}`;

    if (!targetArtist) {
      alert('Please enter the target artist name.');
      return;
    }

    if (!destArtist) { // Enter a placeholder destination artist name
      destArtist = "Adele";
      providedDestArtist = false;
    }

    section1.expand();
    section2.expand();

    table1.renderLoading();
    table2.renderLoading();

    try {
      if (!window.SDSToken) {
        throw new Error('Missing SDS token on client side.');
      }
      // -----------------------------
      // STEP 1: Start BFS jobs
      // DEPRECATED: RUNNING SEARCH EVERY TIME IS UNNECESSARY AND COSTS TOO MUCH
      // INSTEAD WE CALL THE BACKEND DIRECTLY TO GET NEIGHBORS
      // -----------------------------

      // const startSearch = (start, target) =>
      //   fetch('/api/search/start', {
      //     method: 'POST',
      //     headers: {
      //       'Content-Type': 'application/json',
      //       'X-SDS-Token': window.SDSToken
      //     },
      //     body: JSON.stringify({ start, target, depth: 1 })
      //   });

      // const searchRes = await startSearch(targetArtist, destArtist);
      // startSearch(destArtist, targetArtist); // fire-and-forget reverse search

      // if (!searchRes.ok) {
      //   const text = await searchRes.text();
      //   throw new Error(`Search start failed: ${searchRes.status} - ${text}`);
      // }

      // const searchData = await searchRes.json();
      // if (!searchData.jobID) {
      //   throw new Error('No jobID returned from search start');
      // }

      // const jobID = searchData.jobID;
      // startAutoExpansion();

      // -----------------------------
      // STEP 2: Fetch artist lookups
      // -----------------------------
      await new Promise(r => setTimeout(r, 5000));

      const [targetData, destData] = await Promise.all([
        fetchWithRetry(`/api/artist/neighbors?name=${encodeURIComponent(targetArtist)}`, 20000, 2000),
        fetchWithRetry(`/api/artist/neighbors?name=${encodeURIComponent(destArtist)}`, 20000, 2000)
      ]);
      console.log('[STEP 2] Fetched target artist data:', targetData);
      console.log('[STEP 2] Fetched destination artist data:', destData);

      const srcArtistId = targetData.ID || targetData.id;
      const dstArtistId = destData.ID || destData.id;

      // -----------------------------
      // STEP 3: Render table1 (real connections)
      // -----------------------------
      const targetTableData = normalizeNeighborsResponse(targetData).map(row => ({
        ...row,
        prob: 1
      }));

      table1.init(targetTableData);

      // -----------------------------
      // STEP 4: Fetch & inject track details (table1) — BATCHED
      // -----------------------------
      console.log("[STEP 4] Getting these trackGIDs:",targetData)
      console.log(
          '[DEBUG] First neighbor:',
          targetData.Neighbors?.[0]
        );

        console.log(
          '[DEBUG] First track:',
          targetData.Neighbors?.[0]?.Tracks?.[0]
        );
      // 1. Collect unique recording GIDs from targetData
      const trackGIDs = Array.from(
        new Set(
          (targetData.Neighbors || [])
            .flatMap(n => n.Tracks || [])
            .map(t => t.recordingID || t.RecordingID || t.recording_gid) // ← THIS IS THE KEY
            .filter(Boolean)
        )
      );

      if (trackGIDs.length === 0) {
        console.log('[STEP 4] No track GIDs found, skipping track feature lookup');
      } else {
        console.log('[STEP 4] Fetching track features for GIDs:', trackGIDs);

        // 2. Single batched POST to backend
        const res = await fetch('/trackLookup', {
          method: 'POST',
          redirect: 'manual',  
          headers: {
            'Content-Type': 'application/json',
            'X-SDS-Token': window.SDSToken,
          },
          body: JSON.stringify({ gids: trackGIDs }),
        });

        // console.log('[trackLookup] status:', res.status);
        // console.log('[trackLookup] redirected:', res.redirected);
        // console.log('[trackLookup] url:', res.url);

        const data = await res.json();
        // console.log('[trackLookup json]', data);

        if (!res.ok) {
          throw new Error(`trackLookup failed: ${res.status}`);
        }

        const { featuresMap = {} } = data;
        /**
         * Expected backend response shape:
         * {
         *   featuresMap: {
         *     "<recording_gid>": { ...RecordingFeatures }
         *   }
         * }
         */

        // console.log('[STEP 4] Received track features:', featuresMap);

        // 3. Inject features into existing table1 rows
        const dt = table1.getInstance();

        console.log('[STEP 4] featuresMap keys:', Object.keys(featuresMap));
        console.log('[STEP 4] Sample feature entry:', Object.values(featuresMap)[0]);

        dt.rows().every(function () {
          const row = this.data();

          // Merge track features per track
          const enrichedTracks = (row.tracks || []).map(track => {
            // Try all possible field names for the recording GID
            const gid =
              track.recordingGID ||     // mixed case
              track.RecordingID ||      // PascalCase
              track.recordingID ||      // camelCase (most common from API)
              track.recording_gid ||    // snake_case
              track.id;                 // fallback

            const features = featuresMap[gid] || {};

            if (gid && Object.keys(features).length > 0) {
              console.log(`[STEP 4] Matched track "${track.recordingName || track.name}" with GID: ${gid}`);
            }

            return {
              ...track,
              ...features,
            };
          });

          // Deduplicate similar-named tracks, keeping ones with features
          const dedupedTracks = deduplicateTracksByName(enrichedTracks);
          if (dedupedTracks.length < enrichedTracks.length) {
            console.log(`[STEP 4] Deduped tracks for "${row.featuredWith}": ${enrichedTracks.length} → ${dedupedTracks.length}`);
          }

          // Update row data (immutable update)
          this.data({
            ...row,
            tracks: dedupedTracks,
            numberOfTracks: dedupedTracks.length,
          });
        });

        // 4. Redraw without resetting pagination
        dt.rows().invalidate().draw(false);

        console.log('[STEP 4] Track features injected into table1');
      }

      // -----------------------------
      // STEP 5: Fetch + render table2 (synthetic)
      // -----------------------------
      // Starting Table2

      // Uses SynthManager for polling with DB cache, cancellation, and client-side cache.
      // Backend checks synthetic_tracks DB first; only calls ML service on cache miss.
      console.log('[STEP 5] Fetching synthetic connections via SynthManager...');

      let synthData;
      try {
        synthData = await synthManager.fetch(
          srcArtistId,
          providedDestArtist === true ? dstArtistId : null,
          { limit: 100, intervalMs: 5000, timeoutMs: 360000 }
        );
      } catch (err) {
        if (err.name === 'AbortError') {
          console.log('[STEP 5] Synth fetch was cancelled (user re-searched)');
          return; // Exit handler — a new one is already running
        }
        throw err; // Re-throw non-abort errors to the outer catch
      }

      console.log('[STEP 5] Fetched synthetic connections:', synthData);

      // Collect all artist GIDs that need name resolution
      // Handle different possible field names from ML service
      const artistGIDs = new Set();
      let srcArtistGID = synthData.src_artist_id || synthData.srcArtist || synthData.srcArtistId;
      console.log('[STEP 5] synthData keys:', Object.keys(synthData));
      console.log('[STEP 5] Source artist GID:', srcArtistGID);
      if (srcArtistGID) {
        artistGIDs.add(srcArtistGID);
      }
      (synthData.neighbors || []).forEach(pred => {
        let dstGID = pred.dst_artist_id || pred.dstArtist || pred.dstArtistId;
        console.log('[STEP 5] Prediction dst GID:', dstGID, 'from pred:', pred);
        if (dstGID) {
          artistGIDs.add(dstGID);
        }
      });

      // Resolve artist GIDs to names
      let artistNamesMap = {};
      if (artistGIDs.size > 0) {
        console.log('[STEP 5] Resolving artist GIDs to names:', Array.from(artistGIDs));
        try {
          const namesRes = await fetch('/artistLookupByGID', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-SDS-Token': window.SDSToken,
            },
            body: JSON.stringify({ gids: Array.from(artistGIDs) }),
          });
          console.log('[STEP 5] artistLookupByGID response status:', namesRes.status);
          if (namesRes.ok) {
            const namesData = await namesRes.json();
            console.log('[STEP 5] Raw response from artistLookupByGID:', namesData);
            artistNamesMap = namesData.artistNames || {};
            console.log('[STEP 5] Resolved artist names map:', artistNamesMap);
            console.log('[STEP 5] Number of resolved names:', Object.keys(artistNamesMap).length);
          } else {
            const errorText = await namesRes.text();
            console.error('[STEP 5] artistLookupByGID failed:', namesRes.status, errorText);
          }
        } catch (err) {
          console.error('[STEP 5] Failed to resolve artist names:', err);
        }
      }

      // Build synthData.Neighbors with resolved names
      const srcArtistName = artistNamesMap[srcArtistGID] || srcArtistGID || 'Unknown Artist';
      synthData.name = srcArtistName; // Set the source artist name for normalizeNeighborsResponse
      console.log('[STEP 5] Source artist name resolved to:', srcArtistName);

      synthData.Neighbors = synthData.neighbors.map(pred => {
        let dstGID = pred.dst_artist_id || pred.dstArtist || pred.dstArtistId;
        const resolvedName = artistNamesMap[dstGID] || pred.dst_artist_name || pred.dstArtistName || dstGID || 'Unknown Artist';
        console.log('[STEP 5] Neighbor GID', dstGID, '-> name:', resolvedName);
        return {
          Name: resolvedName,
          Tracks: pred.tracks,
          probability: pred.probability,
          dstArtistId: dstGID,
          srcArtistId: srcArtistGID,
        };
      });

      // Deduplicate neighbors with similar names (different artist_ids but same/similar name)
      const beforeDedup = synthData.Neighbors.length;
      synthData.Neighbors = deduplicateNeighborsByName(synthData.Neighbors);
      if (synthData.Neighbors.length < beforeDedup) {
        console.log(`[STEP 5] Deduped similar-named neighbors: ${beforeDedup} → ${synthData.Neighbors.length}`);
      }

      // Render table2
      console.log('[STEP 5] synthData after name resolution:', synthData);
      const synthTableData = normalizeNeighborsResponse(synthData);
      table2.init(synthTableData);

      // -----------------------------
      // STEP 5b: Fetch track features for table2 (synthetic)
      // -----------------------------
      // Guard: if user re-searched during Step 5, bail out
      const currentSearchId = `${mlStartInput.value.trim()}::${mlTargetInput.value.trim()}`;
      if (currentSearchId !== searchId) {
        console.log('[STEP 5b] Search changed, skipping stale track feature fetch');
        return;
      }

      // Collect all synthetic track IDs (these are integers from your DB)
      const synthTrackIDs = Array.from(
        new Set(
          (synthData.Neighbors || synthData.neighbors || [])
            .flatMap(n => n.Tracks || n.tracks || [])
            .filter(Boolean)
        )
      );

      if (synthTrackIDs.length > 0) {
        console.log('[STEP 5b] Fetching track features for synthetic connections:', synthTrackIDs.length);
        console.log('[STEP 5b] Sample synthetic track IDs:', synthTrackIDs.slice(0, 10));

        const synthRes = await fetch('/ml/synth/tracks', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-SDS-Token': window.SDSToken,
          },
          body: JSON.stringify({ gids: synthTrackIDs }),
        });

        if (synthRes.ok) {
          const synthFeatureData = await synthRes.json();
          const synthFeaturesMap = synthFeatureData.featuresMap || {};

          console.log('[STEP 5b] Received synthetic track features:', Object.keys(synthFeaturesMap).length);
          console.log('[STEP 5b] synthFeaturesMap keys:', Object.keys(synthFeaturesMap));
          console.log('[STEP 5b] Sample synthetic feature entry:', Object.values(synthFeaturesMap)[0]);

          // Inject into table2
          const dt2 = table2.getInstance();
          if (dt2) {
            const allRows = dt2.rows().data();
            
            // Process each row
            for (let i = 0; i < allRows.length; i++) {
              const row = allRows[i];
              
              const enrichedTracks = (row.tracks || []).map(track => {
                // The track is just an integer from your ML response
                const trackId = typeof track === "object"
                  ? (track.recordingID || track.recording_gid || track.recordingGID || 
                    track.RecordingID || track.id || track.track_id)
                  : track;
                
                // Convert to string for consistent key lookup
                const trackIdStr = String(trackId);
                const features = synthFeaturesMap[trackIdStr] || {};

                if (trackIdStr && Object.keys(features).length > 0) {
                  console.log(`[STEP 5b] Matched synthetic track ID: ${trackIdStr}`);
                  console.log(`[STEP 5b] Features:`, features);
                } else {
                  console.warn(`[STEP 5b] No features found for synthetic track ID: ${trackIdStr}`);
                }

                return {
                  // Include basic track info
                  id: trackId,
                  track_id: trackIdStr,
                  // Spread all the features from your Go struct
                  ...features,
                };
              });
              
              // Update the row with enriched tracks
              dt2.row(i).data({ ...row, tracks: enrichedTracks });
            }
            
            // Redraw the table
            dt2.draw(false);
            console.log('[STEP 5b] Track features injected into table2');
          }
        }
      }

      // -----------------------------
      // STEP 6: Poll BFS job
      // -----------------------------
      // pollJob(jobID); // Removing this because we removed the BFS from this page

    } catch (err) {
      console.error(err);
      alert(`Error: ${err.message}`);
      table1.renderEmpty();
      table2.renderEmpty();
    } finally {
      const mlSpinner = document.getElementById('spinner');
      mlSpinner?.classList.remove('visible');
    }
  };
});

/**
 * Generate sample data for demonstration
 * Remove this in production and use actual API data
 */
function generateSampleData() {
  return [
    {
      artist_name: 'Sample Artist',
      genre: 'Rock',
      popularity: 85,
      followers: 1234567,
      active_years: 15,
      albums: 8,
      top_track: 'Sample Song',
      collaboration_score: 0.78,
    },
    {
      artist_name: 'Another Artist',
      genre: 'Pop',
      popularity: 92,
      followers: 2345678,
      active_years: 10,
      albums: 5,
      top_track: 'Hit Single',
      collaboration_score: 0.65,
    },
    {
      artist_name: 'Third Artist',
      genre: 'Electronic',
      popularity: 73,
      followers: 987654,
      active_years: 8,
      albums: 6,
      top_track: 'Dance Track',
      collaboration_score: 0.82,
    },
  ];
}
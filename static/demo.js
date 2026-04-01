/* =========================================
   Interlude API Demo — Frontend JS
   Calls /api/v1/* endpoints directly
========================================= */

const API_BASE = window.location.origin;

// ---- DOM Helpers ----
const $ = (sel) => document.querySelector(sel);
const show = (el) => { if (typeof el === 'string') el = $(el); if (el) el.style.display = ''; };
const hide = (el) => { if (typeof el === 'string') el = $(el); if (el) el.style.display = 'none'; };

function probClass(p) {
  if (p >= 0.65) return 'high';
  if (p >= 0.4) return 'medium';
  return 'low';
}

function loading(container, msg = 'Loading...') {
  if (typeof container === 'string') container = $(container);
  container.innerHTML = `<div class="loading-inline"><div class="spinner-sm"></div>${msg}</div>`;
}

// ---- API Calls ----
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers: { ...headers, ...opts.headers } });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const err = await res.json();
      detail = err.detail || err.message || JSON.stringify(err);
    } catch { detail += ': ' + await res.text(); }
    throw new Error(detail);
  }
  return res.json();
}

// ---- Predict Connection ----
async function predictConnection() {
  const src = $('#srcInput').value.trim();
  const dst = $('#dstInput').value.trim();
  if (!src || !dst) return alert('Enter both artists');

  show('#connectionCard');

  $('#srcBadge').textContent = src;
  $('#dstBadge').textContent = dst;
  $('#probValue').textContent = '...';
  $('#probRing').className = 'prob-ring';
  $('#connectionMeta').innerHTML = '<div class="loading-inline"><div class="spinner-sm"></div>Running ML pipeline — this can take up to 30 seconds for uncached artists...</div>';

  try {
    const res = await api('/api/v1/predict/connection', {
      method: 'POST',
      body: JSON.stringify({ src_artist: src, dst_artist: dst, limit: 5 }),
    });

    const d = res.data;
    const m = res.meta;
    const prob = d.probability;

    if (d.src_name) $('#srcBadge').textContent = d.src_name;
    if (d.dst_name) $('#dstBadge').textContent = d.dst_name;

    const pct = (prob * 100).toFixed(2);
    $('#probValue').textContent = `${pct}%`;
    $('#probRing').className = `prob-ring ${probClass(prob)}`;

    $('#connectionMeta').innerHTML = `
      <span>Model: <span class="meta-tag">${m.model_version}</span></span>
      <span>Latency: <span class="meta-tag">${m.latency_ms.toFixed(0)}ms</span></span>
      <span>Cached: <span class="meta-tag">${m.cached ? 'yes' : 'no'}</span></span>
    `;

  } catch (e) {
    $('#connectionMeta').innerHTML = `<span style="color:var(--error);">${e.message}</span>`;
  }
}

// ---- Neighbor Discovery ----
async function discoverNeighbors() {
  const artist = $('#neighborInput').value.trim();
  if (!artist) return alert('Enter an artist');

  show('#neighborsCard');
  $('#neighborsTitle').textContent = 'Predicted Collaborators';
  $('#neighborsBody').innerHTML = '<tr><td colspan="4"><div class="loading-inline"><div class="spinner-sm"></div>Running ML pipeline — this can take up to 60 seconds for uncached artists...</div></td></tr>';

  try {
    const res = await api('/api/v1/predict/neighbors', {
      method: 'POST',
      body: JSON.stringify({ artist, limit: 50 }),
    });

    const d = res.data;
    const title = d.artist_name ? `Top Predicted Collaborators for ${d.artist_name}` : 'Top Predicted Collaborators';
    $('#neighborsTitle').textContent = title;

    let neighbors = d.neighbors || [];
    if (neighbors.length === 0) {
      $('#neighborsBody').innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-muted);">No neighbors found</td></tr>';
      return;
    }

    // Sort descending by probability, show top 10
    neighbors.sort((a, b) => b.probability - a.probability);
    neighbors = neighbors.slice(0, 10);

    $('#neighborsBody').innerHTML = neighbors.map((n, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${escHtml(n.name || n.artist_id)}</td>
        <td><span class="prob-badge ${probClass(n.probability)}">${(n.probability * 100).toFixed(2)}%</span></td>
        <td>${(n.tracks || []).length} tracks</td>
      </tr>
    `).join('');
  } catch (e) {
    $('#neighborsBody').innerHTML = `<tr><td colspan="4" style="color:var(--error);">${e.message}</td></tr>`;
  }
}

// ---- Utility ----
function escHtml(str) {
  const div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

// ---- Artist Autocomplete ----
let artistNameList = [];

async function loadArtistNames() {
  try {
    const res = await fetch('/static/top_artists.txt');
    if (!res.ok) return [];
    const text = await res.text();
    artistNameList = text.split('\n').map(x => x.trim()).filter(Boolean);
    return artistNameList;
  } catch { return []; }
}

function createAutocomplete(inputEl) {
  const container = inputEl.closest('.autocomplete-container');
  if (!container) return;
  const listEl = container.querySelector('.autocomplete-list');
  if (!listEl) return;
  let currentIndex = -1;

  function closeList() {
    listEl.style.display = 'none';
    listEl.innerHTML = '';
    currentIndex = -1;
  }

  async function updateSuggestions() {
    const q = inputEl.value.trim();
    if (!q) return closeList();
    if (!artistNameList.length) await loadArtistNames();
    const lc = q.toLowerCase();
    const starts = artistNameList.filter(n => n.toLowerCase().startsWith(lc));
    const contains = artistNameList.filter(n => !n.toLowerCase().startsWith(lc) && n.toLowerCase().includes(lc));
    const suggestions = [...starts, ...contains].slice(0, 15);
    listEl.innerHTML = '';
    if (!suggestions.length) return closeList();
    suggestions.forEach(name => {
      const item = document.createElement('div');
      item.className = 'autocomplete-item';
      item.setAttribute('role', 'option');
      item.innerHTML = `
        <div class="autocomplete-left">
          <div class="autocomplete-name">${escHtml(name)}</div>
        </div>
        <div class="autocomplete-tag">Artist</div>`;
      item.addEventListener('mousedown', e => {
        e.preventDefault();
        inputEl.value = name;
        closeList();
      });
      listEl.appendChild(item);
    });
    listEl.style.display = 'block';
  }

  inputEl.addEventListener('input', updateSuggestions);
  inputEl.addEventListener('focus', updateSuggestions);
  inputEl.addEventListener('blur', () => setTimeout(closeList, 120));
  inputEl.addEventListener('keydown', e => {
    const items = Array.from(listEl.querySelectorAll('.autocomplete-item'));
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      currentIndex = (currentIndex + 1) % items.length;
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      currentIndex = (currentIndex - 1 + items.length) % items.length;
    } else if (e.key === 'Enter') {
      if (currentIndex >= 0) {
        e.preventDefault();
        inputEl.value = items[currentIndex].querySelector('.autocomplete-name').textContent;
        closeList();
      }
      return;
    } else { return; }
    items.forEach((item, idx) => item.setAttribute('aria-selected', idx === currentIndex));
  });
}

// ---- Event Listeners ----
document.addEventListener('DOMContentLoaded', () => {
  loadArtistNames();

  // Autocomplete on artist inputs
  createAutocomplete($('#srcInput'));
  createAutocomplete($('#dstInput'));
  createAutocomplete($('#neighborInput'));

  $('#predictBtn').addEventListener('click', predictConnection);
  $('#neighborBtn').addEventListener('click', discoverNeighbors);

  // Enter key support
  $('#srcInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') predictConnection(); });
  $('#dstInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') predictConnection(); });
  $('#neighborInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') discoverNeighbors(); });
});
